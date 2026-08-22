"""화면이 호출하는 엔진 진입점.

채점 공식은 domain.scoring(12축, 8직군, TOP 5)을 그대로 쓴다.
P3 뼈대만 옮긴다: 세션·버전 저장, 선택 입력은 점수 밖, API 실패 시 스냅샷 상세.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from db import repository as repo
from db import seed as seeder
from domain.branching import build_user_profile
from domain.scoring import ENGINE_VERSION, rank_job_families
from services.explainer import prior_test_notes
from services.personality import heard_summary, personality_profile
from services.work24 import job_family_detail

ROOT = Path(__file__).resolve().parent
_NON_DIAGNOSTIC = {"PRIOR_TEST"}


def _load(name: str) -> dict[str, Any]:
    return json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))


def bootstrap(db_path=None) -> dict[str, int]:
    """앱 시작 시 한 번. 스키마 생성 + JSON seed. 여러 번 돌려도 안전하다."""
    return seeder.run(db_path, verbose=False)


def versions() -> dict[str, str]:
    return seeder.versions()


def screen_copy() -> dict[str, Any]:
    return _load("copy.json")["screens"]


def start_session(consent_version: str = "v1", db_path=None) -> str:
    session_id = repo.create_session(consent_version, ENGINE_VERSION, db_path)
    repo.log_event(session_id, "diagnosis_started", ENGINE_VERSION, screen="landing", db_path=db_path)
    return session_id


def save_prior_test(session_id: str, mbti=None, enneagram=None, db_path=None) -> None:
    """MBTI·에니어그램은 점수에 넣지 않는다. 맥락으로만 저장한다."""
    repo.save_response(
        session_id,
        "PRIOR_TEST",
        {"mbti": mbti, "enneagram": enneagram},
        db_path=db_path,
    )


def answer(session_id: str, question_id: str, value, shown_order=None, db_path=None) -> None:
    repo.save_response(session_id, question_id, value, shown_order, db_path)
    repo.log_event(session_id, "question_answered", ENGINE_VERSION, screen="diagnose", db_path=db_path)


def diagnostic_answers(session_id: str, db_path=None) -> dict[str, Any]:
    return {key: value for key, value in repo.load_responses(session_id, db_path).items() if key not in _NON_DIAGNOSTIC}


def compute(
    session_id: str,
    responses: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    optional_traits: dict[str, Any] | None = None,
    db_path=None,
    top_n: int = 5,
) -> dict[str, Any]:
    """12축 적합도를 계산하고 버전과 함께 저장한다. LLM은 순위에 영향을 주지 않는다."""
    answers = responses if responses is not None else diagnostic_answers(session_id, db_path)
    questions = _load("questions.json")
    profiles = _load("job_profiles.json")
    user_vector, clusters = build_user_profile(questions, answers)
    ranked = rank_job_families(user_vector, profiles["job_families"], top_n=top_n)

    repo.save_responses(session_id, answers, db_path)
    repo.save_profile(
        session_id,
        user_vector,
        clusters,
        context=context,
        optional_traits=optional_traits,
        db_path=db_path,
    )
    repo.save_recommendations(session_id, ranked, versions(), db_path)
    repo.complete_session(session_id, db_path)
    repo.log_event(session_id, "result_viewed", ENGINE_VERSION, screen="result", db_path=db_path)

    job_name = ranked[0]["name"] if ranked else ""
    return {
        "session_id": session_id,
        "user_vector": user_vector,
        "clusters": clusters,
        "top": ranked,
        "heard": heard_summary(user_vector),
        "prior_test": prior_test_notes(optional_traits, job_name),
        "profile": personality_profile(user_vector),
        "tie_notice": bool(ranked and ranked[0].get("close_score")),
        "versions": versions(),
    }


def get_family_detail(job_family_id: str, session_id: str | None = None, db_path=None) -> dict[str, Any]:
    """직군 상세. 실시간 API가 실패해도 스냅샷으로 채운다."""
    families = _load("job_profiles.json")["job_families"]
    family = next((item for item in families if item["job_family_id"] == job_family_id), None)
    if family is None:
        raise ValueError(f"없는 직군입니다: {job_family_id}")
    detail = job_family_detail(job_family_id)
    if session_id:
        repo.log_event(
            session_id,
            "job_detail_viewed",
            ENGINE_VERSION,
            screen="detail",
            job_family_id=job_family_id,
            db_path=db_path,
        )
    return {
        "job_family_id": family["job_family_id"],
        "name": family["name"],
        "description": family.get("description", ""),
        "occupations": detail["occupations"],
        "used_live_api": detail.get("used_live_api", False),
        "source_label": detail.get("source_label", ""),
    }


def save_feedback(session_id: str, rating, reason=None, db_path=None) -> None:
    repo.save_feedback(session_id, rating, reason, db_path)
    repo.log_event(session_id, "feedback_submitted", ENGINE_VERSION, screen="feedback", db_path=db_path)


def replay(session_id: str, db_path=None) -> dict[str, Any] | None:
    return repo.replay(session_id, db_path)
