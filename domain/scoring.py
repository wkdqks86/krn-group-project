"""적합도 계산. LLM과 분리된 순수 함수만 둔다."""

from __future__ import annotations

from typing import Any

AXES = [
    "R",
    "I",
    "A",
    "S",
    "E",
    "C",
    "problem_solving",
    "logical",
    "collaboration",
    "communication",
    "persistence",
    "self_management_execution",
]

AXIS_LABELS = {
    "R": "현실형 활동 선호",
    "I": "탐구형 활동 선호",
    "A": "예술형 활동 선호",
    "S": "사회형 활동 선호",
    "E": "진취형 활동 선호",
    "C": "관습형 활동 선호",
    "problem_solving": "문제해결",
    "logical": "논리적 사고",
    "collaboration": "협업",
    "communication": "의사소통",
    "persistence": "지속성",
    "self_management_execution": "자기관리·실행",
}

LIKERT_WEIGHT = 0.70
SJT_WEIGHT = 0.30
SJT_PRIMARY_POINTS = 2
SJT_SECONDARY_POINTS = 1
CLOSE_SCORE_GAP = 3.0
ENGINE_VERSION = "0.1.0"


def empty_axis_map(default: float = 0.0) -> dict[str, float]:
    return {axis: default for axis in AXES}


def likert_to_100(values: list[float]) -> float:
    """1~5 리커트 평균을 0~100으로 정규화한다."""
    if not values:
        raise ValueError("리커트 응답이 없습니다.")
    average = sum(values) / len(values)
    return (average - 1.0) / 4.0 * 100.0


def combine_user_axis(likert_100: float, sjt_100: float | None) -> float:
    if sjt_100 is None:
        return likert_100
    return LIKERT_WEIGHT * likert_100 + SJT_WEIGHT * sjt_100


def normalize_sjt_raw(raw_points: dict[str, float], max_points: dict[str, float]) -> dict[str, float | None]:
    scores: dict[str, float | None] = {}
    for axis in AXES:
        ceiling = max_points.get(axis, 0.0)
        if ceiling <= 0:
            scores[axis] = None
            continue
        scores[axis] = min(100.0, raw_points.get(axis, 0.0) / ceiling * 100.0)
    return scores


def build_user_vector(
    likert_by_axis: dict[str, list[float]],
    sjt_scores: dict[str, float | None],
) -> dict[str, float]:
    user_vector = empty_axis_map()
    for axis in AXES:
        # 아직 답하지 않은 축은 '낮다'가 아니라 '모른다'이므로 중립 3점으로 둔다.
        # `.get(axis, [3.0])`만으로는 부족하다. 호출부가 모든 축을 빈 리스트로 미리
        # 채워 두면 키가 존재해서 기본값이 적용되지 않고 likert_to_100이 예외를 던진다.
        values = likert_by_axis.get(axis) or [3.0]
        likert_100 = likert_to_100(values)
        user_vector[axis] = combine_user_axis(likert_100, sjt_scores.get(axis))
    return user_vector


def fit_score(
    user_vector: dict[str, float],
    requirement_vector: dict[str, float],
    axis_weight: dict[str, float],
) -> float:
    numerator = 0.0
    denominator = 0.0
    for axis in AXES:
        weight = float(axis_weight[axis])
        user = float(user_vector[axis]) / 100.0
        requirement = float(requirement_vector[axis]) / 100.0
        numerator += weight * user * requirement
        denominator += weight * requirement
    if denominator == 0:
        return 0.0
    return 100.0 * numerator / denominator


def band_for_rank(rank: int) -> str:
    if rank == 1:
        return "가장 높은 탐색 우선순위"
    if rank in (2, 3):
        return "높은 탐색 우선순위"
    return "함께 탐색"


def top_component_scores(
    user_vector: dict[str, float],
    requirement_vector: dict[str, float],
    axis_weight: dict[str, float],
    limit: int = 3,
) -> list[dict[str, Any]]:
    scored = []
    for axis in AXES:
        contribution = (
            float(axis_weight[axis])
            * (float(user_vector[axis]) / 100.0)
            * (float(requirement_vector[axis]) / 100.0)
        )
        scored.append(
            {
                "axis": axis,
                "label": AXIS_LABELS[axis],
                "user": round(user_vector[axis], 1),
                "requirement": round(requirement_vector[axis], 1),
                "weight": axis_weight[axis],
                "contribution": round(contribution, 4),
            }
        )
    scored.sort(key=lambda item: item["contribution"], reverse=True)
    return scored[:limit]


def caution_axes(
    user_vector: dict[str, float],
    requirement_vector: dict[str, float],
    axis_weight: dict[str, float],
    limit: int = 1,
) -> list[dict[str, Any]]:
    gaps = []
    for axis in AXES:
        gap = float(requirement_vector[axis]) - float(user_vector[axis])
        if gap < 15:
            continue
        gaps.append(
            {
                "axis": axis,
                "label": AXIS_LABELS[axis],
                "user": round(user_vector[axis], 1),
                "requirement": round(requirement_vector[axis], 1),
                "weight": axis_weight[axis],
                "gap": round(gap, 1),
            }
        )
    gaps.sort(key=lambda item: (item["weight"], item["gap"]), reverse=True)
    return gaps[:limit]


def rank_job_families(
    user_vector: dict[str, float],
    job_families: list[dict[str, Any]],
    top_n: int = 5,
) -> list[dict[str, Any]]:
    ranked = []
    for family in job_families:
        total = fit_score(
            user_vector,
            family["requirement_vector"],
            family["axis_weight"],
        )
        ranked.append(
            {
                "job_family_id": family["job_family_id"],
                "name": family["name"],
                "description": family.get("description", ""),
                "total": round(total, 1),
                "component_scores": top_component_scores(
                    user_vector,
                    family["requirement_vector"],
                    family["axis_weight"],
                ),
                "cautions": caution_axes(
                    user_vector,
                    family["requirement_vector"],
                    family["axis_weight"],
                ),
            }
        )
    ranked.sort(key=lambda item: (-item["total"], item["job_family_id"]))
    close_top = False
    if len(ranked) >= 2 and abs(ranked[0]["total"] - ranked[1]["total"]) < CLOSE_SCORE_GAP:
        close_top = True

    results = []
    for index, item in enumerate(ranked[:top_n], start=1):
        results.append(
            {
                **item,
                "rank": index,
                "band": band_for_rank(index),
                "close_score": close_top and index <= 2,
            }
        )
    return results
