"""미리 계산된 점수·근거를 문장으로만 바꾼다. 점수를 다시 계산하지 않는다."""

from __future__ import annotations

from typing import Any

from domain.scoring import AXIS_LABELS


def template_reasons(recommendation: dict[str, Any]) -> list[str]:
    lines = []
    for item in recommendation.get("component_scores", [])[:3]:
        lines.append(
            f"{item['label']} 응답({item['user']:.0f})이 이 직군의 초기 프로파일({item['requirement']:.0f})과 가깝습니다."
        )
    return lines


def template_cautions(recommendation: dict[str, Any], context: dict[str, Any] | None = None) -> list[str]:
    lines = []
    for item in recommendation.get("cautions", [])[:1]:
        lines.append(
            f"{item['label']}은 이 직군 초기 프로파일에서 상대적으로 높게 잡혀 있습니다. "
            "실제 업무에서 이 요소가 얼마나 자주 쓰이는지 더 확인해 보세요."
        )
    context = context or {}
    if context.get("work_style") == "개인 작업 선호" and recommendation["job_family_id"] in {"J04", "J05", "J07", "J08"}:
        lines.append("대면·협업 비중이 높은 편일 수 있어, 실제 근무 환경을 공고와 함께 확인해 보세요.")
    if not lines:
        lines.append("점수가 높더라도 채용 자격이나 성공 가능성을 뜻하지 않습니다.")
    return lines[:2]


def explain_recommendation(
    recommendation: dict[str, Any],
    context: dict[str, Any] | None = None,
    use_llm: bool = False,
) -> dict[str, list[str]]:
    """LLM 사용 여부와 관계없이 같은 구조화 데이터를 입력으로 받는다."""
    payload = {
        "reasons": template_reasons(recommendation),
        "cautions": template_cautions(recommendation, context),
    }
    if use_llm:
        # 발표 안정성을 위해 기본은 템플릿. LLM은 이후 adapter에서만 호출한다.
        return payload
    return payload


def axis_summary(user_vector: dict[str, float]) -> list[str]:
    ranked = sorted(user_vector.items(), key=lambda item: item[1], reverse=True)
    return [f"{AXIS_LABELS[axis]} {score:.0f}" for axis, score in ranked[:3]]
