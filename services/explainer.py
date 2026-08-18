"""미리 계산된 점수·근거를 문장으로만 바꾼다. 점수를 다시 계산하지 않는다.

문구는 data/copy.json(P2 소유)에서 읽는다. 파일이 없으면 안전한 기본 문구로 동작한다.
톤앤보이스 규칙: 사용자 응답을 인용한 뒤 응원, 결핍어·단정어·예측어 금지, 감탄사·이모지 없음.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from domain.scoring import AXIS_LABELS

_COPY_PATH = Path(__file__).resolve().parents[1] / "data" / "copy.json"

_FALLBACK = {
    "reason_template": "‘{label}’ 쪽으로 답이 기울었어요. 이 직군이 그 힘을 오래 쓰는 자리예요.",
    "caution_template": "이 직군은 ‘{label}’ 쪽을 자주 쓰는 편이에요. 실제 업무에서 어느 정도인지 공고와 함께 확인해 보면 좋아요.",
    "caution_fallback": "점수가 높아도 합격 가능성이나 능력을 뜻하진 않아요. 관심이 가면 공고부터 한 번 열어보면 좋아요.",
    "work_style_caution": "대면·협업 비중이 있는 편이에요. 실제 근무 방식이 나와 맞는지 공고로 확인해 보면 좋아요.",
}


def _load_result_copy() -> dict[str, Any]:
    try:
        data = json.loads(_COPY_PATH.read_text(encoding="utf-8"))
        return {**_FALLBACK, **data.get("result", {})}
    except (OSError, ValueError):
        return dict(_FALLBACK)


_RESULT_COPY = _load_result_copy()


def template_reasons(recommendation: dict[str, Any]) -> list[str]:
    template = _RESULT_COPY["reason_template"]
    lines = []
    for item in recommendation.get("component_scores", [])[:3]:
        lines.append(template.format(label=item["label"]))
    return lines


def template_cautions(recommendation: dict[str, Any], context: dict[str, Any] | None = None) -> list[str]:
    template = _RESULT_COPY["caution_template"]
    lines = []
    for item in recommendation.get("cautions", [])[:1]:
        lines.append(template.format(label=item["label"]))

    context = context or {}
    if context.get("work_style") == "개인 작업 선호" and recommendation["job_family_id"] in {"J04", "J05", "J07", "J08"}:
        lines.append(_RESULT_COPY["work_style_caution"])
    if not lines:
        lines.append(_RESULT_COPY["caution_fallback"])
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
