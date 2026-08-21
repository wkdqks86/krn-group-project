import json
from pathlib import Path

from domain.scoring import rank_job_families
from services.explainer import explain_recommendation, template_cautions

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
