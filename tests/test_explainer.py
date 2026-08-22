import json
from pathlib import Path

from domain.scoring import rank_job_families
from services.explainer import explain_recommendation, prior_test_notes, template_cautions

ROOT = Path(__file__).resolve().parents[1]


def load_json(name: str):
    return json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))


def _top_recommendation(user_vector: dict[str, float]) -> dict:
    families = load_json("job_profiles.json")["job_families"]
    return rank_job_families(user_vector, families)[0]


def test_context_work_style_adds_caution_for_high_team_job():
    user = {axis: 70 for axis in load_json("job_profiles.json")["axes"]}
    recommendation = _top_recommendation(user)
    context = {"work_style": "개인 작업 선호"}

    cautions = template_cautions(recommendation, context)

    assert any("개인 작업" in line for line in cautions)
    assert any(recommendation["name"] in line for line in cautions)


def test_context_without_work_style_keeps_environment_caption():
    user = {axis: 70 for axis in load_json("job_profiles.json")["axes"]}
    recommendation = _top_recommendation(user)

    cautions = template_cautions(recommendation, None)

    assert len(cautions) >= 1
    assert not any("입력하셨어요" in line for line in cautions)


def test_context_education_and_career_surface_in_cautions():
    user = {axis: 55 for axis in load_json("job_profiles.json")["axes"]}
    recommendation = _top_recommendation(user)
    context = {
        "education": "학사",
        "career": "신입",
        "work_style": None,
    }

    cautions = template_cautions(recommendation, context)

    assert any("학사" in line for line in cautions)
    assert any("신입" in line for line in cautions)


def test_context_region_surface_when_room_available():
    user = {axis: 55 for axis in load_json("job_profiles.json")["axes"]}
    recommendation = _top_recommendation(user)
    context = {"region": ["서울"], "work_style": None}

    cautions = template_cautions(recommendation, context)

    assert any("서울" in line for line in cautions)


def test_explain_recommendation_passes_context_through():
    user = {axis: 60 for axis in load_json("job_profiles.json")["axes"]}
    recommendation = _top_recommendation(user)
    context = {"work_style": "개인 작업 선호"}

    explained = explain_recommendation(recommendation, context, user_vector=user)

    assert explained["reasons"]
    assert any("개인 작업" in line for line in explained["cautions"])


def test_prior_test_notes_are_reading_lens_not_empty():
    lines = prior_test_notes({"mbti": "ISFP", "enneagram": "9"}, "교육·공공")
    assert any("점수·순위" in line for line in lines)
    assert any("혼자 충전" in line for line in lines)
    assert any("사람 맥락" in line for line in lines)
    assert any("조율·중재" in line for line in lines)
    assert any("교육·공공" in line for line in lines)


def test_prior_test_notes_skip_when_empty():
    assert prior_test_notes({}, "IT·데이터") == []
    assert prior_test_notes({"mbti": None, "enneagram": None}, "IT·데이터") == []
