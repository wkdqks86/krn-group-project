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
        "1": "‘{label}’ 응답이 가장 도드라졌어요. {job_name}에서는 이 힘이 핵심으로 꼽히는 축이에요 — {example} 같은 일에서 특히 자주 쓰여요. 답변 전반에서 이 축의 응답이 뚜렷하게 높게 나타난 결과예요.",
        "2": "‘{label}’ 쪽 응답도 함께 두드러졌어요. {job_name}에서 이 힘은 {example} 업무를 할 때 자주 쓰여요. 이 축 역시 여러 문항에서 안정적으로 나타난 응답이라 함께 눈여겨볼 만해요.",
        "3": "‘{label}’ 성향도 답에 반영됐어요. {job_name} 안에서는 이 힘이 다른 축을 보조하는 역할로 쓰이는 편이에요. 단독으로 가장 두드러지진 않아도 앞선 두 힘과 맞물리면 자연스럽게 쓰일 수 있어요.",
    },
    "caution_template": "이 직군은 ‘{label}’ 쪽을 특히 자주 씁니다. {job_name}의 {example} 같은 공고를 직접 열어서, 실제 업무 강도가 지금 느낌과 맞는지 확인해 보면 좋아요. 공고의 ‘자격요건’과 ‘우대사항’을 나눠서 보면, 필수로 요구되는 수준인지 아니면 있으면 좋은 정도인지 구분하는 데 도움이 돼요.",
    "caution_fallback": "점수가 높아도 합격 가능성이나 능력을 뜻하진 않아요. 관심이 가면 공고부터 한 번 열어보면 좋아요.",
    "environment_captions": {
        "face_to_face": "이 직군은 사람을 직접 마주하는 비중이 있는 편이에요. 대면 소통이 잦을 수 있어요. 사람을 상대하는 시간이 부담스럽지 않은지 미리 가늠해보면 좋아요.",
        "team_interaction": "이 직군은 팀과 자주 맞춰가며 일하는 편이에요. 협업 빈도가 잦을 수 있어요. 혼자 처리하는 시간보다 조율하는 시간이 길 수 있다는 점을 염두에 두면 좋아요.",
        "change_speed": "이 직군은 상황이 자주 바뀌는 편이에요. 계획을 자주 조정해야 할 수 있어요. 계획이 자주 바뀌는 상황에서 스트레스를 크게 받는 편인지 스스로 점검해보면 좋아요.",
        "quantitative_work": "이 직군은 수치·데이터를 다루는 비중이 있는 편이에요. 숫자 기반 업무가 자주 나올 수 있어요. 숫자를 다루는 일이 익숙하지 않다면, 관련 툴(엑셀·통계 등) 사용 경험을 먼저 점검해보면 좋아요.",
    },
    "actions_heading": "지금 해볼 수 있는 것",
    "action_keyword_template": "‘{example}’ 같은 키워드로 공고를 검색해서 실제 업무 범위를 먼저 확인해 보세요. 공고의 ‘주요업무’ 항목을 보면 실제로 어떤 일을 반복하게 되는지 감을 잡을 수 있어요.",
    "growth_heading": "보완하면 좋은 부분",
    "growth_intro_template": "이 직군에서도 어느 정도 쓰는 힘인데, 지금 답변에서는 상대적으로 덜 드러났어요.",
    "growth_empty": "지금 답변 기준으로는 이 직군에서 특별히 보완할 부분이 두드러지지 않아요.",
    "glossary_heading": "공고 볼 때 참고할 점",
    "glossary_template": "‘{occupation}’ 같은 공고에서는 흔히 이런 표현이 나와요 — {hint}",
    "context_captions": {
        "work_style_solo_high_team": "업무 방식으로 ‘개인 작업’을 선택하셨어요. {job_name}은 팀 조율이 잦은 편이라, 공고의 ‘근무환경’·‘주요업무’에서 혼자 처리하는 시간과 함께 일하는 시간 비중을 함께 확인해 보면 좋아요.",
        "work_style_team_low_team": "업무 방식으로 ‘팀 작업’을 선택하셨어요. {job_name}은 혼자 몰입하는 시간 비중이 큰 편일 수 있어요. 공고에서 독립 수행·집중 업무 비중을 같이 보면 좋아요.",
        "work_style_solo_high_face": "업무 방식으로 ‘개인 작업’을 선택하셨어요. {job_name}은 대면 소통이 잦은 편이라, 실제 현장에서 사람을 마주하는 시간이 어느 정도인지 공고를 통해 확인해 보면 좋아요.",
        "region_selected": "희망 근무지역({regions})을 입력하셨어요. {job_name} 관련 공고를 볼 때 해당 지역 필터와 채용 규모를 함께 확인해 보면 좋아요.",
        "education_provided": "최종 학력({education})을 입력하셨어요. {job_name} 공고의 ‘자격요건’에서 학력 조건이 필수인지, 경력·자격으로 대체 가능한지 구분해 보면 좋아요.",
        "career_fresh": "경력을 ‘신입’으로 입력하셨어요. {job_name} 공고에서 ‘신입’·‘경력무관’ 표기와 실제 요구 역량을 나란히 보면 좋아요.",
        "career_experienced": "경력을 ‘경험 있음’으로 입력하셨어요. {job_name} 공고의 ‘우대사항’과 ‘필수요건’을 나눠서, 기존 경험이 어디까지 인정될 수 있는지 확인해 보면 좋아요.",
    },
}

_ENV_ORDER = ["face_to_face", "team_interaction", "change_speed", "quantitative_work"]
_ENV_HIGH = 4
_ENV_LOW = 2
_GROWTH_WEIGHT_THRESHOLD = 0.06
_CAUTION_LINE_LIMIT = 3


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
_PRIOR_TEST = _load_json(_COPY_PATH).get("prior_test", {})


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


def _context_caution_lines(
    context: dict[str, Any] | None,
    job_name: str,
    env: dict[str, Any],
) -> tuple[list[str], bool]:
    """현실 조건 입력을 주의 문구로 변환한다. (lines, 근무환경 캡션 중복 여부)."""
    if not context:
        return [], False

    captions = _RESULT_COPY.get("context_captions", {})
    lines: list[str] = []
    covers_environment = False

    work_style = context.get("work_style")
    team_level = env.get("team_interaction", 0)
    face_level = env.get("face_to_face", 0)

    if work_style == "개인 작업 선호" and team_level >= _ENV_HIGH:
        lines.append(captions["work_style_solo_high_team"].format(job_name=job_name))
        covers_environment = True
    elif work_style == "팀 작업 선호" and team_level <= _ENV_LOW:
        lines.append(captions["work_style_team_low_team"].format(job_name=job_name))
        covers_environment = True

    if work_style == "개인 작업 선호" and face_level >= _ENV_HIGH and len(lines) < 2:
        lines.append(captions["work_style_solo_high_face"].format(job_name=job_name))
        covers_environment = True

    education = context.get("education")
    if education and len(lines) < 2:
        lines.append(
            captions["education_provided"].format(education=education, job_name=job_name)
        )

    career = context.get("career")
    if career == "신입" and len(lines) < 2:
        lines.append(captions["career_fresh"].format(job_name=job_name))
    elif career == "경험 있음" and len(lines) < 2:
        lines.append(captions["career_experienced"].format(job_name=job_name))

    regions = [region for region in (context.get("region") or []) if region != "상관없음"]
    if regions and len(lines) < 2:
        lines.append(
            captions["region_selected"].format(regions=", ".join(regions), job_name=job_name)
        )

    return lines[:2], covers_environment


def template_cautions(recommendation: dict[str, Any], context: dict[str, Any] | None = None) -> list[str]:
    template = _RESULT_COPY["caution_template"]
    job_name = recommendation.get("name", "이 직군")
    job_family_id = recommendation.get("job_family_id", "")
    lines = []
    for item in recommendation.get("cautions", [])[:1]:
        example = _example_for(job_family_id, 0)
        lines.append(template.format(label=item["label"], job_name=job_name, example=example))

    env = _FAMILY_CONTEXT.get(job_family_id, {}).get("environment_json", {})
    context_lines, skip_env_caption = _context_caution_lines(context, job_name, env)
    lines.extend(context_lines)

    if not skip_env_caption:
        env_captions = _RESULT_COPY["environment_captions"]
        top_env_axis = max(
            (axis for axis in _ENV_ORDER if env.get(axis, 0) >= _ENV_HIGH),
            key=lambda axis: env.get(axis, 0),
            default=None,
        )
        if top_env_axis and top_env_axis in env_captions:
            lines.append(env_captions[top_env_axis])

    if not lines:
        lines.append(_RESULT_COPY["caution_fallback"])
    return lines[:_CAUTION_LINE_LIMIT]


def action_lines(recommendation: dict[str, Any]) -> list[str]:
    """이 직군에서 강점으로 쓰이는 상위 축(최대 2개)을 기준으로, 지금 준비할 수 있는 구체적 행동을 안내한다."""
    job_family_id = recommendation.get("job_family_id", "")
    component_scores = recommendation.get("component_scores", [])
    lines = []
    seen_axes = set()
    for item in component_scores[:2]:
        axis = item["axis"]
        if axis in seen_axes:
            continue
        action_text = _PERSONALITY_CONTENT["axis_action_text"].get(axis)
        if action_text:
            lines.append(action_text)
            seen_axes.add(axis)
    keyword = _example_for(job_family_id, 0)
    lines.append(_RESULT_COPY["action_keyword_template"].format(example=keyword))
    return lines


def growth_alignment_lines(recommendation: dict[str, Any], user_vector: dict[str, float] | None) -> list[str]:
    """사용자의 하위 축 중, 이 직군이 실제로 어느 정도 비중 있게 쓰는 축을 최대 2개까지 짚어 준다."""
    if not user_vector:
        return [_RESULT_COPY["growth_empty"]]

    job_family_id = recommendation.get("job_family_id", "")
    axis_weight = _FAMILY_CONTEXT.get(job_family_id, {}).get("axis_weight", {})
    growth_text = _PERSONALITY_CONTENT["axis_growth_text"]

    ranked_low = sorted(AXES, key=lambda axis: user_vector.get(axis, 0))
    candidates = [
        axis
        for axis in ranked_low[:6]
        if axis_weight.get(axis, 0) >= _GROWTH_WEIGHT_THRESHOLD and axis in growth_text
    ]
    if not candidates:
        return [_RESULT_COPY["growth_empty"]]

    ranked_candidates = sorted(candidates, key=lambda axis: axis_weight.get(axis, 0), reverse=True)
    intro = _RESULT_COPY["growth_intro_template"]
    lines = []
    for axis in ranked_candidates[:2]:
        label = AXIS_LABELS.get(axis, axis)
        lines.append(f"‘{label}’ — {intro} {growth_text[axis]}")
    return lines


def glossary_lines(recommendation: dict[str, Any]) -> list[str]:
    """이 직군 대표 직업 최대 2개의 실제 education_hint(팀 검수 스냅샷)를 그대로 인용한다. 새로 지어내지 않는다."""
    job_family_id = recommendation.get("job_family_id", "")
    occupations = _OCCUPATIONS_BY_FAMILY.get(job_family_id, [])
    template = _RESULT_COPY["glossary_template"]
    lines = []
    for occ in occupations[:2]:
        hint = occ.get("snapshot_json", {}).get("education_hint")
        if not hint:
            continue
        lines.append(template.format(occupation=occ["name"], hint=hint))
    return lines


def prior_test_notes(
    optional_traits: dict[str, Any] | None,
    job_name: str,
) -> list[str]:
    """MBTI·에니어그램은 순위를 바꾸지 않고, 1위 직군을 읽는 렌즈로만 쓴다."""
    traits = optional_traits or {}
    mbti = str(traits.get("mbti") or "").strip().upper()
    enneagram = str(traits.get("enneagram") or "").strip()
    labels = []
    if len(mbti) == 4 and mbti.isalpha():
        labels.append(mbti)
    if enneagram in (_PRIOR_TEST.get("enneagram") or {}):
        labels.append(f"에니어그램 {enneagram}")
    if not labels:
        return []

    job = job_name or "이 직군"
    lines = [_PRIOR_TEST.get("score_note", "입력하신 {traits}는 점수에 넣지 않았어요.").format(traits=" · ".join(labels))]
    letters = _PRIOR_TEST.get("mbti_letters") or {}
    if len(mbti) == 4:
        for index in (0, 2):
            template = letters.get(mbti[index])
            if template:
                lines.append(template.format(job_name=job))
    enneagram_map = _PRIOR_TEST.get("enneagram") or {}
    if enneagram in enneagram_map:
        lines.append(enneagram_map[enneagram].format(job_name=job))
    return lines


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
