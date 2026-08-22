"""현재 제품 정의(12축·8직군·TOP 5) 위에서 엔진 진입점을 검증한다."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import engine
from db import repository as repo
from domain.branching import build_user_profile, visible_question_queue
from domain.scoring import rank_job_families

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = json.loads((ROOT / "data" / "questions.json").read_text(encoding="utf-8"))
JOB_PROFILES = json.loads((ROOT / "data" / "job_profiles.json").read_text(encoding="utf-8"))


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    engine.bootstrap(path)
    return path


def sample_responses():
    responses: dict = {}
    for _ in range(3):
        queue = visible_question_queue(QUESTIONS, responses)
        remaining = [item for item in queue if item["question_id"] not in responses]
        if not remaining:
            break
        for question in remaining:
            if question["type"] == "likert":
                responses[question["question_id"]] = 3
            else:
                responses[question["question_id"]] = question["options"][0]["option_id"]
    return responses


def test_bootstrap_is_idempotent(db):
    first = engine.bootstrap(db)
    second = engine.bootstrap(db)
    assert first == second
    assert first["job_families"] == 8


def test_compute_matches_domain_ranking(db):
    responses = sample_responses()
    expected_vector, _clusters = build_user_profile(QUESTIONS, responses)
    expected = rank_job_families(expected_vector, JOB_PROFILES["job_families"], top_n=5)

    session_id = engine.start_session(db_path=db)
    result = engine.compute(session_id, responses=responses, db_path=db)

    assert [item["job_family_id"] for item in result["top"]] == [item["job_family_id"] for item in expected]
    assert [item["total"] for item in result["top"]] == [item["total"] for item in expected]
    assert len(result["top"]) == 5
    assert result["heard"]["headline"]
    assert result["versions"]["engine_version"] == engine.versions()["engine_version"]


def test_prior_test_does_not_change_score(db):
    responses = sample_responses()
    session_id = engine.start_session(db_path=db)
    before = engine.compute(session_id, responses=responses, db_path=db)
    engine.save_prior_test(session_id, mbti="INTJ", enneagram="5", db_path=db)
    after = engine.compute(
        session_id,
        responses=responses,
        optional_traits={"mbti": "INTJ", "enneagram": "5"},
        db_path=db,
    )
    assert [item["total"] for item in before["top"]] == [item["total"] for item in after["top"]]
    assert after["prior_test"]
    assert any("INTJ" in line for line in after["prior_test"])


def test_feedback_does_not_change_score(db):
    responses = sample_responses()
    session_id = engine.start_session(db_path=db)
    result = engine.compute(session_id, responses=responses, db_path=db)
    before = [item["total"] for item in result["top"]]
    engine.save_feedback(session_id, "도움 됨", "이유가 이해됐다", db_path=db)
    saved = repo.load_recommendations(session_id, db)
    assert [item["total"] for item in saved] == before


def test_same_input_replays(db):
    responses = sample_responses()
    session_id = engine.start_session(db_path=db)
    result = engine.compute(session_id, responses=responses, db_path=db)
    replayed = engine.replay(session_id, db)
    assert replayed["session"]["status"] == "completed"
    assert [item["job_family_id"] for item in replayed["recommendations"]] == [
        item["job_family_id"] for item in result["top"]
    ]


def test_detail_works_without_live_api(db):
    detail = engine.get_family_detail("J03", db_path=db)
    assert detail["occupations"]
    assert detail["used_live_api"] is False


def test_unknown_family_raises(db):
    with pytest.raises(ValueError, match="없는 직군"):
        engine.get_family_detail("J99", db_path=db)
