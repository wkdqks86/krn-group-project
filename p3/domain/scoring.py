"""직군 적합도 계산과 순위. 순수 함수만 둔다.

같은 입력은 항상 같은 결과를 낸다. LLM은 이 모듈을 호출하지도, 호출당하지도 않는다.
"""
from p3.domain import content

ENV_SCALE = 25  # 1~5 척도를 0~100 격차로 환산
CONTEXT_ENV_WEIGHT = 0.70
CONTEXT_RULE_WEIGHT = 0.30
TIE_GAP = 3.0  # 이 차이 미만이면 동등 탐색군으로 안내

FULL_WEIGHTS = {"interest": 0.25, "competency": 0.35, "personality": 0.20, "context": 0.20}
# ContextFit이 없을 때는 나머지를 합 1.0으로 재정규화한다 (0.25/0.35/0.20 → /0.80)
CORE_WEIGHTS = {"interest": 0.3125, "competency": 0.4375, "personality": 0.25}


def _element_fit(user_val, target_val, is_environment=False):
    diff = abs(user_val - target_val)
    if is_environment:
        diff *= ENV_SCALE
    return max(0.0, 100.0 - diff)


def _group_fit(user, target, weight, is_environment=False):
    num = den = 0.0
    for axis, w in weight.items():
        num += w * _element_fit(user[axis], target[axis], is_environment)
        den += w
    if den == 0:
        return 50.0
    return num / den


def context_fit(profile, family, context_rule_score=50.0):
    """업무환경 유사도 70% + 지역·연봉·경력 규칙 점수 30%.

    규칙 점수는 P5의 직업 매핑이 확정되기 전까지 중립 50 고정이다.
    조건이 성향 결과를 과도하게 뒤집지 않도록 상한을 30%로 묶어 둔 것은 PRD §10의 결정이다.
    """
    env = profile.get("environment")
    if env is None:
        return None
    axis_names = content.axes()["environment"]
    even = {a: 1.0 / len(axis_names) for a in axis_names}
    env_fit = _group_fit(env, family["environment"], even, is_environment=True)
    return CONTEXT_ENV_WEIGHT * env_fit + CONTEXT_RULE_WEIGHT * context_rule_score


def score_family(profile, family, context_rule_score=50.0):
    interest = _group_fit(profile["riasec"], family["riasec_target"], family["riasec_weight"])
    competency = _group_fit(profile["competency"], family["competency_target"], family["competency_weight"])
    personality = _group_fit(profile["big5"], family["big5_target"], family["big5_weight"])
    ctx = context_fit(profile, family, context_rule_score)

    if ctx is None:
        w = CORE_WEIGHTS
        total = w["interest"] * interest + w["competency"] * competency + w["personality"] * personality
    else:
        w = FULL_WEIGHTS
        total = (
            w["interest"] * interest
            + w["competency"] * competency
            + w["personality"] * personality
            + w["context"] * ctx
        )

    return {
        "job_family_id": family["job_family_id"],
        "name": family["name"],
        "one_liner": family["one_liner"],
        "total": round(total, 1),
        "component_scores": {
            "interest": round(interest, 1),
            "competency": round(competency, 1),
            "personality": round(personality, 1),
            "context": round(ctx, 1) if ctx is not None else None,
        },
    }


def rank(profile, context_rule_scores=None):
    """8개 직군을 점수순으로 정렬한다.

    동점 규칙: total → CompetencyFit → InterestFit → 직군 ID.
    ID까지 내려가면 완전한 전순서가 되므로 결과가 절대 흔들리지 않는다.
    """
    context_rule_scores = context_rule_scores or {}
    results = [
        score_family(profile, fam, context_rule_scores.get(fam["job_family_id"], 50.0))
        for fam in content.job_profiles()["job_families"]
    ]
    results.sort(
        key=lambda r: (
            -r["total"],
            -r["component_scores"]["competency"],
            -r["component_scores"]["interest"],
            r["job_family_id"],
        )
    )
    for i, r in enumerate(results, 1):
        r["rank"] = i
    return results


# --- 밴드 -----------------------------------------------------------------


def band_for(total, top_score, rank_position):
    """밴드는 절대 점수가 아니라 그 세션 1위와의 차이로 정한다.

    8개 직군 점수가 63.8~89.9에 몰려서 절대 경계로는 변별이 안 된다는 P2 실측 결과를 따른다.
    상위 3개는 '먼저 들여다볼 만한 세 갈래'로 제시되므로 밴드 바닥을 깐다.
    """
    bands = content.result_copy()["bands"]
    levels = bands["levels"]
    delta = top_score - total

    idx = len(levels) - 1
    for i, level in enumerate(levels):
        if level["max_delta"] is None or delta <= level["max_delta"]:
            idx = i
            break

    floor = bands.get("top_band_floor")
    if floor and rank_position <= floor["rank_lte"]:
        floor_idx = next(i for i, lv in enumerate(levels) if lv["label"] == floor["min_label"])
        idx = min(idx, floor_idx)

    return levels[idx]


def annotate_bands(ranked):
    """순위 목록에 밴드 라벨과 근거 문장 개수를 붙인다."""
    if not ranked:
        return ranked
    top = ranked[0]["total"]
    for r in ranked:
        level = band_for(r["total"], top, r["rank"])
        r["band"] = level["label"]
        r["reason_count"] = level["reason_count"]
        r["collapsed"] = level["collapsed"] and r["rank"] > content.result_copy()["bands"]["always_show_top"]
    return ranked


def is_tie(ranked):
    """1~2위 차이가 작으면 '순서는 큰 의미가 없어요' 안내를 띄운다."""
    return len(ranked) >= 2 and (ranked[0]["total"] - ranked[1]["total"]) < TIE_GAP


def largest_gap_axis(profile, family):
    """가장 격차가 큰 축 하나. 접힘 카드의 '거리의 이유' 문구를 고를 때 쓴다."""
    candidates = []
    for group, target_key, weight_key in (
        ("riasec", "riasec_target", "riasec_weight"),
        ("big5", "big5_target", "big5_weight"),
    ):
        for axis, w in family[weight_key].items():
            gap = family[target_key][axis] - profile[group][axis]
            if gap > 0:
                # 가중치가 큰 축의 격차가 더 크게 아프다
                candidates.append((gap * w, f"{group}.{axis}"))
    if not candidates:
        return None
    return max(candidates)[1]
