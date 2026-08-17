import json
from pathlib import Path

from domain.branching import (
    build_user_profile,
    select_clusters,
    visible_question_queue,
)
from domain.scoring import (
    ENGINE_VERSION,
    fit_score,
    likert_to_100,
    rank_job_families,
)

ROOT = Path(__file__).resolve().parents[1]


def load_json(name: str):
    return json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))


def test_likert_normalization():
    assert likert_to_100([1]) == 0
    assert likert_to_100([5]) == 100
    assert likert_to_100([3]) == 50
    assert likert_to_100([1, 5]) == 50


def test_fit_score_bounds():
    weights = {axis: 1 / 12 for axis in load_json("job_profiles.json")["axes"]}
    high = {axis: 100 for axis in weights}
    low = {axis: 0 for axis in weights}
    mid = {axis: 50 for axis in weights}
    assert fit_score(high, high, weights) == 100
    assert fit_score(low, high, weights) == 0
    assert fit_score(mid, high, weights) == 50


def test_job_profile_weights_sum_to_one():
    payload = load_json("job_profiles.json")
    for family in payload["job_families"]:
        total = sum(family["axis_weight"].values())
        assert abs(total - 1.0) < 1e-9, family["job_family_id"]


def test_same_input_same_ranking():
    families = load_json("job_profiles.json")["job_families"]
    user = {axis: 70 for axis in load_json("job_profiles.json")["axes"]}
    user["I"] = 90
    user["logical"] = 88
    user["problem_solving"] = 85
    first = rank_job_families(user, families)
    second = rank_job_families(user, families)
    assert first == second
    assert first[0]["job_family_id"] == "J03"
    assert ENGINE_VERSION == "0.1.0"


def test_cluster_tie_prefers_first_choice():
    counts = {"analyze": 2, "people": 2, "execute": 0}
    assert select_clusters(counts, first_choice_cluster="people")[0] == "people"


def test_complete_path_stays_within_required_range():
    questions = load_json("questions.json")
    responses = {}
    for question in questions["questions"]:
        if question["type"] == "likert":
            responses[question["question_id"]] = 4
        elif question["module"] == "sjt_common":
            responses[question["question_id"]] = question["options"][0]["option_id"]

    queue = visible_question_queue(questions, responses)
    required = [item for item in queue if item.get("required")]
    assert 24 <= len(required) <= 28

    for item in queue:
        if item["type"] == "sjt" and item["question_id"] not in responses:
            responses[item["question_id"]] = item["options"][0]["option_id"]

    user_vector, clusters = build_user_profile(questions, responses)
    assert len(user_vector) == 12
    assert len(clusters) == 2
    ranked = rank_job_families(user_vector, load_json("job_profiles.json")["job_families"])
    assert len(ranked) == 5
    assert ranked[0]["total"] >= ranked[-1]["total"]
