"""SJT 공통 문항 응답으로 후속 질문 클러스터를 고른다."""

from __future__ import annotations

from collections import Counter
from typing import Any

from domain.scoring import (
    AXES,
    SJT_PRIMARY_POINTS,
    SJT_SECONDARY_POINTS,
    build_user_vector,
    empty_axis_map,
    normalize_sjt_raw,
)

CLUSTER_ORDER = ["analyze", "people", "execute", "craft"]


def question_map(questions_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["question_id"]: item for item in questions_payload["questions"]}


def likert_questions(questions_payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in questions_payload["questions"]
        if item["type"] == "likert" and item["module"] in {"riasec", "competency"}
    ]


def common_sjt_questions(questions_payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in questions_payload["questions"] if item["module"] == "sjt_common"]


def followup_questions_for_clusters(
    questions_payload: dict[str, Any],
    clusters: list[str],
) -> list[dict[str, Any]]:
    selected = []
    for cluster in clusters:
        selected.extend(
            [
                item
                for item in questions_payload["questions"]
                if item.get("module") == "sjt_followup" and item.get("cluster") == cluster
            ]
        )
    return selected


def option_by_id(question: dict[str, Any], option_id: str) -> dict[str, Any]:
    for option in question.get("options", []):
        if option["option_id"] == option_id:
            return option
    raise KeyError(f"선택지를 찾을 수 없습니다: {option_id}")


def accumulate_sjt(
    questions: list[dict[str, Any]],
    responses: dict[str, str],
) -> tuple[dict[str, float], dict[str, float], Counter]:
    raw = empty_axis_map()
    maximum = empty_axis_map()
    clusters: Counter = Counter()

    for question in questions:
        response_id = responses.get(question["question_id"])
        if not response_id:
            continue
        chosen = option_by_id(question, response_id)
        raw[chosen["primary"]] += SJT_PRIMARY_POINTS
        raw[chosen["secondary"]] += SJT_SECONDARY_POINTS
        if "cluster" in chosen:
            clusters[chosen["cluster"]] += 1
        for axis in maximum:
            question_max = 0
            for option in question["options"]:
                points = 0
                if option["primary"] == axis:
                    points = SJT_PRIMARY_POINTS
                elif option["secondary"] == axis:
                    points = SJT_SECONDARY_POINTS
                question_max = max(question_max, points)
            maximum[axis] += question_max

    return raw, maximum, clusters


def select_clusters(cluster_counts: Counter, first_choice_cluster: str | None = None) -> list[str]:
    if not cluster_counts:
        return CLUSTER_ORDER[:2]

    ranked = sorted(
        cluster_counts.items(),
        key=lambda item: (-item[1], CLUSTER_ORDER.index(item[0]) if item[0] in CLUSTER_ORDER else 99),
    )
    top_score = ranked[0][1]
    tied = [name for name, score in ranked if score == top_score]
    if len(tied) > 1 and first_choice_cluster in tied:
        ordered = [first_choice_cluster] + [name for name in tied if name != first_choice_cluster]
        rest = [name for name, _score in ranked if name not in ordered]
        ordered.extend(rest)
    else:
        ordered = [name for name, _score in ranked]

    for name in CLUSTER_ORDER:
        if name not in ordered:
            ordered.append(name)
        if len(ordered) >= 2:
            break
    return ordered[:2]


def first_sjt_cluster(questions_payload: dict[str, Any], responses: dict[str, str]) -> str | None:
    common = common_sjt_questions(questions_payload)
    if not common:
        return None
    first = common[0]
    option_id = responses.get(first["question_id"])
    if not option_id:
        return None
    return option_by_id(first, option_id).get("cluster")


def visible_question_queue(
    questions_payload: dict[str, Any],
    responses: dict[str, str],
) -> list[dict[str, Any]]:
    """리커트 → 공통 SJT → (응답이 있으면) 후속 문항 순으로 노출 목록을 만든다."""
    queue = likert_questions(questions_payload) + common_sjt_questions(questions_payload)
    common_ids = {item["question_id"] for item in common_sjt_questions(questions_payload)}
    if not common_ids.issubset(responses.keys()):
        return queue

    _raw, _maximum, cluster_counts = accumulate_sjt(
        common_sjt_questions(questions_payload), responses
    )
    clusters = select_clusters(cluster_counts, first_sjt_cluster(questions_payload, responses))
    queue.extend(followup_questions_for_clusters(questions_payload, clusters))
    return queue


def build_user_profile(
    questions_payload: dict[str, Any],
    responses: dict[str, Any],
) -> tuple[dict[str, float], list[str]]:
    likert_by_axis = {axis: [] for axis in AXES}
    for question in likert_questions(questions_payload):
        value = responses.get(question["question_id"])
        if value is None:
            continue
        likert_by_axis[question["axis"]].append(float(value))

    queue = visible_question_queue(questions_payload, responses)
    sjt_items = [item for item in queue if item["type"] == "sjt"]
    raw, maximum, cluster_counts = accumulate_sjt(sjt_items, responses)
    sjt_scores = normalize_sjt_raw(raw, maximum)
    user_vector = build_user_vector(likert_by_axis, sjt_scores)
    clusters = select_clusters(cluster_counts, first_sjt_cluster(questions_payload, responses))
    return user_vector, clusters
