"""SQLite 저장 계층 테스트.

DB 없이도 점수 계산은 돌아야 하고, DB는 계산 결과를 그대로 되살릴 수 있어야 한다.
"""

import json
from pathlib import Path

import pytest

from db import repository as repo
from db import seed
from domain.branching import build_user_profile
from domain.scoring import ENGINE_VERSION, rank_job_families

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = json.loads((ROOT / "data" / "questions.json").read_text(encoding="utf-8"))
JOB_PROFILES = json.loads((ROOT / "data" / "job_profiles.json").read_text(encoding="utf-8"))


@pytest.fixture
def db(tmp_path):
    """테스트마다 임시 DB를 새로 만든다. 실제 potential_discovery.db는 건드리지 않는다."""
    path = tmp_path / "test.db"
    seed.run(path, verbose=False)
    return path


def sample_responses():
    """노출되는 모든 문항에 답한 완전한 응답 한 벌을 만든다.

    문항 파일에서 직접 만들기 때문에 문항이 늘어나도 이 테스트는 그대로 돈다.
    다른 브랜치의 픽스처에 기대지 않으려고 자립형으로 두었다.
    """
    from domain.branching import visible_question_queue

    responses: dict = {}
    for _ in range(3):  # 분기 문항이 드러날 때까지 반복해서 채운다
        queue = visible_question_queue(QUESTIONS, responses)
        remaining = [q for q in queue if q["question_id"] not in responses]
        if not remaining:
            break
        for question in remaining:
            if question["type"] == "likert":
                responses[question["question_id"]] = 3
            else:
                responses[question["question_id"]] = question["options"][0]["option_id"]
    return responses


# --- seed ------------------------------------------------------------------


def test_data_files_are_consistent():
    """seed 전에 data/ 파일끼리 어긋난 곳이 없어야 한다."""
    assert seed.check() == []


def test_seed_creates_all_content(db):
    counts = seed.run(db, verbose=False)
    assert counts["job_families"] == 8
    assert counts["questions"] == len(QUESTIONS["questions"])
    with repo.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) c FROM job_families").fetchone()["c"] == 8
        assert conn.execute("SELECT COUNT(*) c FROM occupations").fetchone()["c"] == counts["occupations"]


def test_seed_is_idempotent(db):
    """여러 번 돌려도 행이 늘지 않아야 한다. 앱이 시작될 때마다 부르기 때문이다."""
    first = seed.run(db, verbose=False)
    second = seed.run(db, verbose=False)
    assert first == second
    with repo.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) c FROM questions").fetchone()["c"] == first["questions"]
        assert conn.execute("SELECT COUNT(*) c FROM question_options").fetchone()["c"] == first["options"]


# --- 세션과 응답 ------------------------------------------------------------


def test_responses_round_trip(db):
    """저장한 응답을 그대로 되읽어 엔진에 바로 넣을 수 있어야 한다."""
    session_id = repo.create_session("v1", ENGINE_VERSION, db)
    responses = sample_responses()
    repo.save_responses(session_id, responses, db)
    assert repo.load_responses(session_id, db) == responses


def test_answering_twice_overwrites(db):
    """사용자가 앞 질문으로 돌아가 답을 바꿀 수 있어야 한다."""
    session_id = repo.create_session("v1", ENGINE_VERSION, db)
    repo.save_response(session_id, "R1", 2, db_path=db)
    repo.save_response(session_id, "R1", 5, db_path=db)
    loaded = repo.load_responses(session_id, db)
    assert loaded["R1"] == 5
    with repo.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) c FROM responses WHERE session_id = ?", (session_id,)).fetchone()["c"] == 1


def test_sessions_do_not_leak_into_each_other(db):
    a = repo.create_session("v1", ENGINE_VERSION, db)
    b = repo.create_session("v1", ENGINE_VERSION, db)
    repo.save_response(a, "R1", 5, db_path=db)
    assert repo.load_responses(b, db) == {}


# --- 결과 재현 --------------------------------------------------------------


def test_result_can_be_replayed(db):
    """PRD의 '재현 가능한 데모' 요구. 저장한 결과가 그대로 되살아나야 한다."""
    session_id = repo.create_session("v1", ENGINE_VERSION, db)
    responses = sample_responses()
    repo.save_responses(session_id, responses, db)

    user_vector, clusters = build_user_profile(QUESTIONS, responses)
    ranked = rank_job_families(user_vector, JOB_PROFILES["job_families"], top_n=8)

    repo.save_profile(session_id, user_vector, clusters, db_path=db)
    repo.save_recommendations(session_id, ranked, seed.versions(), db)
    repo.complete_session(session_id, db)

    replayed = repo.replay(session_id, db)
    assert replayed["session"]["status"] == "completed"
    assert replayed["responses"] == responses
    assert replayed["profile"]["clusters"] == clusters
    assert [r["job_family_id"] for r in replayed["recommendations"]] == [
        r["job_family_id"] for r in ranked
    ]
    for saved, original in zip(replayed["recommendations"], ranked):
        assert saved["total"] == pytest.approx(original["total"])
        assert saved["band"] == original["band"]


def test_recommendations_store_all_versions(db):
    """가중치가 바뀌어도 과거 결과를 재현하려면 버전이 함께 있어야 한다."""
    session_id = repo.create_session("v1", ENGINE_VERSION, db)
    user_vector, _clusters = build_user_profile(QUESTIONS, sample_responses())
    ranked = rank_job_families(user_vector, JOB_PROFILES["job_families"], top_n=8)
    repo.save_recommendations(session_id, ranked, seed.versions(), db)

    saved = repo.load_recommendations(session_id, db)
    versions = seed.versions()
    assert saved[0]["engine_version"] == versions["engine_version"]
    assert saved[0]["question_version"] == versions["question_version"]
    assert saved[0]["job_profile_version"] == versions["job_profile_version"]


def test_recompute_replaces_instead_of_duplicating(db):
    session_id = repo.create_session("v1", ENGINE_VERSION, db)
    user_vector, _clusters = build_user_profile(QUESTIONS, sample_responses())
    ranked = rank_job_families(user_vector, JOB_PROFILES["job_families"], top_n=8)
    repo.save_recommendations(session_id, ranked, seed.versions(), db)
    repo.save_recommendations(session_id, ranked, seed.versions(), db)
    assert len(repo.load_recommendations(session_id, db)) == len(ranked)


# --- 개인정보 · 로그 --------------------------------------------------------


def test_no_personal_identifiers_are_stored(db):
    """이름·연락처·이메일 컬럼이 아예 없어야 한다. 익명 UUID만 쓴다."""
    with repo.connect(db) as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    assert columns == {"user_id", "consent_version", "created_at"}


def test_api_log_keeps_no_secrets(db):
    """인증키가 로그로 새면 안 된다. 해시와 상태만 남긴다."""
    repo.log_api_fetch("work24", "abc123hash", "error:ConnectionError", 3000, db)
    with repo.connect(db) as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM api_fetch_logs")]
    blob = json.dumps(rows, ensure_ascii=False)
    assert "authKey" not in blob and "serviceKey" not in blob
    assert rows[0]["status"].startswith("error:")


def test_feedback_does_not_touch_recommendations(db):
    """피드백은 제품 개선용이지 점수 보정 근거가 아니다."""
    session_id = repo.create_session("v1", ENGINE_VERSION, db)
    user_vector, _clusters = build_user_profile(QUESTIONS, sample_responses())
    ranked = rank_job_families(user_vector, JOB_PROFILES["job_families"], top_n=8)
    repo.save_recommendations(session_id, ranked, seed.versions(), db)
    before = [r["total"] for r in repo.load_recommendations(session_id, db)]

    repo.save_feedback(session_id, "도움 됐어요", "근거가 이해됐어요", db)

    after = [r["total"] for r in repo.load_recommendations(session_id, db)]
    assert before == after


def test_events_record_only_anonymous_fields(db):
    session_id = repo.create_session("v1", ENGINE_VERSION, db)
    repo.log_event(session_id, "result_viewed", ENGINE_VERSION, screen="result", job_family_id="J03", db_path=db)
    with repo.connect(db) as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(events)")}
    assert columns == {
        "event_id", "session_id", "name", "screen", "job_family_id", "engine_version", "created_at"
    }


def test_replay_of_unknown_session_returns_none(db):
    assert repo.replay("존재하지-않는-세션", db) is None
