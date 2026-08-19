"""미리 계산된 점수·근거를 문장으로만 바꾼다. 점수를 다시 계산하지 않는다.

문구는 data/copy.json·data/personality_content.json(P2 소유)에서 읽는다.
직군별 대표 직업(example_occupations)·근무환경(environment_json)·가중치(axis_weight)는
data/job_profiles.json에서, 공고 표현 예시는 data/occupations.json에서 읽어 온다.
파일이 없으면 안전한 기본 문구로 동작한다.
톤앤보이스 규칙: 사용자 응답을 인용한 뒤 응원, 결핍어·단정어·예측어 금지, 감탄사·이모지 없음.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from domain.scoring import AXES, AXIS_LABELS

_ROOT = Path(__file__).resolve().parents[1]
_COPY_PATH = _ROOT / "data" / "copy.json"
_PROFILES_PATH = _ROOT / "data" / "job_profiles.json"
_PERSONALITY_PATH = _ROOT / "data" / "personality_content.json"
_OCCUPATIONS_PATH = _ROOT / "data" / "occupations.json"

_FALLBACK = {
    "reason_templates": {
        "1": "‘{label}’ 응답이 가장 도드라졌어요. {job_name}에서는 이 힘이 핵심으로 꼽히는 축이에요 — {example} 같은 일에서 특히 자주 쓰여요.",
        "2": "‘{label}’ 쪽 응답도 함께 두드러졌어요. {job_name}에서 이 힘은 {example} 업무를 할 때 자주 쓰여요.",
        "3": "‘{label}’ 성향도 답에 반영됐어요. {job_name} 안에서는 이 힘이 다른 축을 보조하는 역할로 쓰이는 편이에요.",
    },
    "caution_template": "이 직군은 ‘{label}’ 쪽을 특히 자주 씁니다. {job_name}의 {example} 같은 공고를 직접 열어서, 실제 업무 강도가 지금 느낌과 맞는지 확인해 보면 좋아요.",
    "caution_fallback": "점수가 높아도 합격 가능성이나 능력을 뜻하진 않아요. 관심이 가면 공고부터 한 번 열어보면 좋아요.",
    "environment_captions": {
        "face_to_face": "이 직군은 사람을 직접 마주하는 비중이 있는 편이에요. 대면 소통이 잦을 수 있어요.",
        "team_interaction": "이 직군은 팀과 자주 맞춰가며 일하는 편이에요. 협업 빈도가 잦을 수 있어요.",
        "change_speed": "이 직군은 상황이 자주 바뀌는 편이에요. 계획을 자주 조정해야 할 수 있어요.",
        "quantitative_work": "이 직군은 수치·데이터를 다루는 비중이 있는 편이에요. 숫자 기반 업무가 자주 나올 수 있어요.",
    },
    "actions_heading": "지금 해볼 수 있는 것",
    "action_keyword_template": "‘{example}’ 같은 키워드로 공고를 검색해서 실제 업무 범위를 먼저 확인해 보세요.",
    "growth_heading": "보완하면 좋은 부분",
    "growth_intro_template": "이 직군에서도 어느 정도 쓰는 힘인데, 지금 답변에서는 상대적으로 덜 드러났어요.",
    "growth_empty": "지금 답변 기준으로는 이 직군에서 특별히 보완할 부분이 두드러지지 않아요.",
    "glossary_heading": "공고 볼 때 참고할 점",
    "glossary_template": "‘{occupation}’ 같은 공고에서는 흔히 이런 표현이 나와요 — {hint}",
}

_ENV_ORDER = ["face_to_face", "team_interaction", "change_speed", "quantitative_work"]
_GROWTH_WEIGHT_THRESHOLD = 0.06


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _load_result_copy() -> dict[str, Any]:
    data = _load_json(_COPY_PATH)
    merged = dict(_FALLBACK)
    merged.update(data.get("result", {}))
    return merged


def _load_family_context() -> dict[str, dict[str, Any]]:
    """job_family_id -> {example_occupations, environment_json, axis_weight}. 점수는 건드리지 않는다."""
    data = _load_json(_PROFILES_PATH)
    return {
        fam["job_family_id"]: {
            "example_occupations": fam.get("example_occupations", []),
            "environment_json": fam.get("environment_json", {}),
            "axis_weight": fam.get("axis_weight", {}),
        }
        for fam in data.get("job_families", [])
    }


def _load_personality_content() -> dict[str, Any]:
    data = _load_json(_PERSONALITY_PATH)
    return {
        "axis_action_text": data.get("axis_action_text", {}),
        "axis_growth_text": data.get("axis_growth_text", {}),
    }


def _load_occupations_by_family() -> dict[str, list[dict[str, Any]]]:
    data = _load_json(_OCCUPATIONS_PATH)
    by_family: dict[str, list[dict[str, Any]]] = {}
    for occ in data.get("occupations", []):
        by_family.setdefault(occ["job_family_id"], []).append(occ)
    return by_family


_RESULT_COPY = _load_result_copy()
_FAMILY_CONTEXT = _load_family_context()
_PERSONALITY_CONTENT = _load_personality_content()
_OCCUPATIONS_BY_FAMILY = _load_occupations_by_family()


def _example_for(job_family_id: str, index: int) -> str:
    examples = _FAMILY_CONTEXT.get(job_family_id, {}).get("example_occupations", [])
    if not examples:
        return "관련 직무"
    return examples[index % len(examples)]


def template_reasons(recommendation: dict[str, Any]) -> list[str]:
    templates = _RESULT_COPY["reason_templates"]
    job_name = recommendation.get("name", "이 직군")
    job_family_id = recommendation.get("job_family_id", "")
    lines = []
    for idx, item in enumerate(recommendation.get("component_scores", [])[:3]):
        template = templates.get(str(idx + 1), templates["3"])
        example = _example_for(job_family_id, idx)
        lines.append(template.format(label=item["label"], job_name=job_name, example=example))
    return lines


def template_cautions(recommendation: dict[str, Any], context: dict[str, Any] | None = None) -> list[str]:
    template = _RESULT_COPY["caution_template"]
    job_name = recommendation.get("name", "이 직군")
    job_family_id = recommendation.get("job_family_id", "")
    lines = []
    for item in recommendation.get("cautions", [])[:1]:
        example = _example_for(job_family_id, 0)
        lines.append(template.format(label=item["label"], job_name=job_name, example=example))

    env = _FAMILY_CONTEXT.get(job_family_id, {}).get("environment_json", {})
    env_captions = _RESULT_COPY["environment_captions"]
    top_env_axis = max(
        (axis for axis in _ENV_ORDER if env.get(axis, 0) >= 4),
        key=lambda axis: env.get(axis, 0),
        default=None,
    )
    if top_env_axis and top_env_axis in env_captions:
        lines.append(env_captions[top_env_axis])

    if not lines:
        lines.append(_RESULT_COPY["caution_fallback"])
    return lines[:2]


def action_lines(recommendation: dict[str, Any]) -> list[str]:
    """이 직군에서 강점으로 쓰이는 상위 축을 기준으로, 지금 준비할 수 있는 구체적 행동 2가지."""
    job_family_id = recommendation.get("job_family_id", "")
    component_scores = recommendation.get("component_scores", [])
    lines = []
    if component_scores:
        top_axis = component_scores[0]["axis"]
        action_text = _PERSONALITY_CONTENT["axis_action_text"].get(top_axis)
        if action_text:
            lines.append(action_text)
    keyword = _example_for(job_family_id, 0)
    lines.append(_RESULT_COPY["action_keyword_template"].format(example=keyword))
    return lines


def growth_alignment_lines(recommendation: dict[str, Any], user_vector: dict[str, float] | None) -> list[str]:
    """사용자의 하위 축 중, 이 직군이 실제로 어느 정도 비중 있게 쓰는 축이 있으면 짚어 준다."""
    if not user_vector:
        return [_RESULT_COPY["growth_empty"]]

    job_family_id = recommendation.get("job_family_id", "")
    axis_weight = _FAMILY_CONTEXT.get(job_family_id, {}).get("axis_weight", {})
    growth_text = _PERSONALITY_CONTENT["axis_growth_text"]

    ranked_low = sorted(AXES, key=lambda axis: user_vector.get(axis, 0))
    candidates = [
        axis
        for axis in ranked_low[:4]
        if axis_weight.get(axis, 0) >= _GROWTH_WEIGHT_THRESHOLD and axis in growth_text
    ]
    if not candidates:
        return [_RESULT_COPY["growth_empty"]]

    target_axis = max(candidates, key=lambda axis: axis_weight.get(axis, 0))
    intro = _RESULT_COPY["growth_intro_template"]
    label = AXIS_LABELS.get(target_axis, target_axis)
    return [f"‘{label}’ — {intro} {growth_text[target_axis]}"]


def glossary_lines(recommendation: dict[str, Any]) -> list[str]:
    """이 직군 대표 직업의 실제 education_hint(팀 검수 스냅샷)를 그대로 인용한다. 새로 지어내지 않는다."""
    job_family_id = recommendation.get("job_family_id", "")
    occupations = _OCCUPATIONS_BY_FAMILY.get(job_family_id, [])
    if not occupations:
        return []
    occ = occupations[0]
    hint = occ.get("snapshot_json", {}).get("education_hint")
    if not hint:
        return []
    template = _RESULT_COPY["glossary_template"]
    return [template.format(occupation=occ["name"], hint=hint)]


def explain_recommendation(
    recommendation: dict[str, Any],
    context: dict[str, Any] | None = None,
    use_llm: bool = False,
    user_vector: dict[str, float] | None = None,
) -> dict[str, list[str]]:
    """LLM 사용 여부와 관계없이 같은 구조화 데이터를 입력으로 받는다."""
    payload = {
        "reasons": template_reasons(recommendation),
        "cautions": template_cautions(recommendation, context),
        "actions": action_lines(recommendation),
        "growth": growth_alignment_lines(recommendation, user_vector),
        "glossary": glossary_lines(recommendation),
    }
    if use_llm:
        # 발표 안정성을 위해 기본은 템플릿. LLM은 이후 adapter에서만 호출한다.
        return payload
    return payload


def axis_summary(user_vector: dict[str, float]) -> list[str]:
    ranked = sorted(user_vector.items(), key=lambda item: item[1], reverse=True)
    return [f"{AXIS_LABELS[axis]} {score:.0f}" for axis, score in ranked[:3]]
