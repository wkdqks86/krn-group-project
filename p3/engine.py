"""P4가 호출하는 유일한 진입점.

Streamlit 화면은 이 함수들만 쓰면 된다. domain·db·services를 직접 import 하지 않아도 된다.
반환값은 전부 평범한 dict/list라 session_state에 그대로 넣을 수 있다.

화면과의 대응
    A 랜딩          start_session()
    B 기존 진단     save_prior_test()
    C 진단 질문     get_core_questions() / answer()
    E 1차 결과      compute(stage="core")
    D 현실 조건     get_deep_questions() / answer()
    E 심화 결과     compute(stage="deep") + compare_stages()
    F 직군 상세     get_family_detail()
    G 피드백        save_feedback()
"""
from p3.db import repository as repo
from p3.db import seed as seeder
from p3.domain import branching, content, profile as profile_mod, scoring
from p3.services import explainer, work24


# --- 초기화 -----------------------------------------------------------------


def bootstrap(db_path=None):
    """앱 시작 시 한 번. 스키마 생성 + P2 JSON seed. 여러 번 돌려도 안전하다."""
    return seeder.run(db_path, verbose=False)


def screen_copy():
    """P4가 화면 문구를 가져가는 곳. 문장을 코드에 하드코딩하지 않게 한다."""
    return content.result_copy()["screen"]


def versions():
    return content.versions()


# --- 진단 흐름 --------------------------------------------------------------


def start_session(consent_version="v1", db_path=None):
    session_id = repo.create_session(consent_version, db_path)
    repo.log_event(session_id, "diagnosis_started", screen="A", db_path=db_path)
    return session_id


def get_core_questions():
    """코어 14문항. order 순이며 P4가 한 문항씩 보여준다.

    역문항 Q05·Q06이 연속 배치되지 않도록 순서를 손볼 때는 reverse 플래그를 보고 판단하면 된다.
    """
    return content.core_questions()


def save_prior_test(session_id, mbti=None, enneagram=None, db_path=None):
    """MBTI·에니어그램은 점수 계산에 반영하지 않는다 (PRD §19 확정).

    맥락으로만 저장하고, 결과 설명에서 참고 문구로만 쓴다.
    """
    repo.save_response(session_id, "PRIOR_TEST", {"mbti": mbti, "enneagram": enneagram}, db_path=db_path)


def answer(session_id, question_id, value, shown_order=None, db_path=None):
    repo.save_response(session_id, question_id, value, shown_order, db_path)
    repo.log_event(session_id, "question_answered", screen="C", db_path=db_path)


def core_progress(session_id, db_path=None):
    answers = _diagnostic_answers(session_id, db_path)
    total = len(content.core_questions())
    done = total - len(branching.missing_core(answers))
    return {"answered": done, "total": total, "complete": done == total}


def get_deep_questions(session_id, db_path=None):
    """분기 결과에 따른 심화 문항. 어떤 경로를 타도 후속 문항 수는 4개로 같다."""
    answers = _diagnostic_answers(session_id, db_path)
    if not branching.is_core_complete(answers):
        raise ValueError(f"코어 문항이 아직 남았습니다: {branching.missing_core(answers)}")
    return {
        "clusters": branching.selected_clusters(answers),
        "questions": branching.deep_questions_for(answers),
    }


# --- 결과 -------------------------------------------------------------------


def compute(session_id, stage="core", db_path=None):
    """점수를 계산하고 저장한 뒤 결과를 돌려준다.

    같은 응답이면 항상 같은 결과가 나온다. LLM 호출 실패나 문구 변경은 순위에 영향을 주지 않는다.
    """
    answers = _diagnostic_answers(session_id, db_path)
    missing = branching.missing_core(answers)
    if missing:
        raise ValueError(f"코어 문항이 아직 남았습니다: {missing}")

    if stage == "core":
        # 1차 결과는 코어 문항만으로 낸다. 심화 응답이 이미 있어도 섞지 않는다.
        core_ids = {q["question_id"] for q in content.core_questions()}
        answers = {k: v for k, v in answers.items() if k in core_ids}

    user_profile = profile_mod.build_profile(answers)
    ranked = scoring.annotate_bands(scoring.rank(user_profile))
    ranked = explainer.explain_all(user_profile, ranked)

    repo.save_profile(session_id, user_profile, db_path)
    repo.save_recommendations(session_id, stage, ranked, content.versions(), db_path)
    repo.set_session_status(
        session_id, "core_done" if stage == "core" else "deep_done", completed=(stage == "deep"), db_path=db_path
    )
    repo.log_event(session_id, "result_viewed", screen="E", db_path=db_path)

    copy = content.result_copy()
    top_n = copy["bands"]["always_show_top"]
    return {
        "session_id": session_id,
        "stage": stage,
        "profile": user_profile,
        "top": ranked[:top_n],
        "rest": ranked[top_n:],
        "all": ranked,
        "tie_notice": copy["screen"]["tie_notice"] if scoring.is_tie(ranked) else None,
        "deep_invite": copy["screen"]["deep_invite"] if stage == "core" else None,
        "confidence": user_profile["confidence"],
        "versions": content.versions(),
    }


def compare_stages(session_id, db_path=None):
    """심화 전후로 순서가 어떻게 달라졌는지. PRD v2의 '변화 표시' 요구사항."""
    core = repo.load_recommendations(session_id, "core", db_path)
    deep = repo.load_recommendations(session_id, "deep", db_path)
    copy = content.result_copy()["screen"]

    if not core or not deep:
        return None

    before = [r["job_family_id"] for r in core]
    after = [r["job_family_id"] for r in deep]
    changed = before[:3] != after[:3]

    return {
        "before": before,
        "after": after,
        "changed": changed,
        "message": copy["deep_changed"] if changed else copy["deep_unchanged"],
        "moves": {
            fid: before.index(fid) - after.index(fid)
            for fid in after
            if fid in before and before.index(fid) != after.index(fid)
        },
    }


def get_family_detail(job_family_id, session_id=None, db_path=None):
    """F 직군 상세. API가 죽어도 스냅샷으로 채워 반환한다."""
    fam = next(
        (f for f in content.job_profiles()["job_families"] if f["job_family_id"] == job_family_id), None
    )
    if fam is None:
        raise ValueError(f"없는 직군입니다: {job_family_id}")

    jobs = work24.occupations_for(job_family_id, db_path)
    if session_id:
        repo.log_event(session_id, "job_detail_viewed", screen="F", job_family_id=job_family_id, db_path=db_path)

    return {
        "job_family_id": fam["job_family_id"],
        "name": fam["name"],
        "one_liner": fam["one_liner"],
        "requirements": {
            "competency": fam["competency_target"],
            "riasec": fam["riasec_target"],
            "big5": fam["big5_target"],
            "environment": fam["environment"],
        },
        "occupations": jobs["occupations"],
        "degraded": jobs["degraded"],
        "notice": jobs["notice"],
    }


def save_feedback(session_id, rating, reason=None, db_path=None):
    """제품 피드백. 점수 보정 근거로 쓰지 않는다."""
    repo.save_feedback(session_id, rating, reason, db_path)
    repo.log_event(session_id, "feedback_submitted", screen="G", db_path=db_path)


# --- 내부 -------------------------------------------------------------------

_NON_DIAGNOSTIC = {"PRIOR_TEST"}


def _diagnostic_answers(session_id, db_path):
    """점수 계산에 들어가는 응답만 남긴다. MBTI 등 선택 입력은 제외한다."""
    return {k: v for k, v in repo.load_answers(session_id, db_path).items() if k not in _NON_DIAGNOSTIC}
