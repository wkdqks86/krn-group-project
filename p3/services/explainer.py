"""설명 어댑터 — 결과 카드의 근거·확인할 점·다음 한 걸음을 만든다.

LLM 경계가 이 모듈의 존재 이유다.

  - 점수·순위·밴드는 이미 domain/scoring.py에서 결정됐다. 여기서 바꾸지 않는다
  - LLM에는 계산이 끝난 구조화 데이터만 넘긴다. 응답 문항 원문이나 개인 맥락은 넘기지 않는다
  - LLM이 실패하거나 5초를 넘으면 템플릿으로 내려간다. 사용자에게 오류를 띄우지 않는다
  - 두 경로의 결과가 톤에서 구분되지 않도록 P2가 템플릿 문장을 먼저 완성해 뒀다
"""
from p3.config import LLM_ENABLED
from p3.domain import content, scoring


def _resolve(rules, profile, limit):
    """when 조건을 평가해 문장을 고른다. default는 항상 마지막 보루로 남긴다."""
    picked, fallback = [], None
    for rule in rules:
        cond = rule["when"]
        if cond == "default":
            fallback = rule["text"]
            continue
        if _evaluate(cond, profile):
            picked.append(rule["text"])
        if len(picked) >= limit:
            break
    if not picked and fallback:
        picked = [fallback]
    return picked[:limit]


def _evaluate(cond, profile):
    """'competency.logical >= 70' 형태만 지원한다.

    eval을 쓰지 않는다. 문구 파일은 P2가 편집하므로, 거기에 임의 코드가 실행될 여지를 두지 않는다.
    """
    try:
        left, op, right = cond.split()
        group, axis = left.split(".")
    except ValueError:
        return False

    bucket = profile.get(group if group != "context" else "environment")
    if not bucket or axis not in bucket:
        return False  # 코어 단계에는 context가 없다. 조건이 걸린 문구는 그냥 건너뛴다.

    value, threshold = bucket[axis], float(right)
    return {
        ">=": value >= threshold,
        "<=": value <= threshold,
        ">": value > threshold,
        "<": value < threshold,
    }.get(op, False)


def build_packet(profile, result, family):
    """LLM에 넘길 입력. result_copy.json의 llm_guard.allowed_input_keys와 일치해야 한다."""
    return {
        "engine_version": content.versions()["engine_version"],
        "job_family_id": result["job_family_id"],
        "rank": result["rank"],
        "band": result["band"],
        "total": result["total"],
        "component_scores": result["component_scores"],
        "top_reasons": result["reasons"],
        "caution_axis": result.get("caution_axis"),
        "user_quotes": [],  # 자유서술은 수집하지 않는다. 인용은 템플릿 문장이 대신한다.
    }


def explain(profile, result):
    """결과 하나에 문구를 채운다. 순위·점수는 건드리지 않는다."""
    copy = content.result_copy()
    fam_copy = copy["families"].get(result["job_family_id"], {})
    family = next(
        f for f in content.job_profiles()["job_families"] if f["job_family_id"] == result["job_family_id"]
    )

    result["reasons"] = _resolve(fam_copy.get("reasons", []), profile, result.get("reason_count", 2))
    cautions = _resolve(fam_copy.get("cautions", []), profile, 1)
    result["caution"] = cautions[0] if cautions else None
    result["next_step"] = (fam_copy.get("next_steps") or [None])[0]
    result["encouragement"] = fam_copy.get("encouragement")

    if result.get("collapsed"):
        axis = scoring.largest_gap_axis(profile, family)
        result["distance_reason"] = copy["distance_reasons"].get(axis)

    if LLM_ENABLED:
        narrated = _try_llm(build_packet(profile, result, family))
        if narrated:
            result["narrative"] = narrated
            result["narrative_source"] = "llm"
        else:
            result["narrative_source"] = "template"
    else:
        result["narrative_source"] = "template"

    return result


def explain_all(profile, ranked):
    return [explain(profile, r) for r in ranked]


def _try_llm(packet):
    """LLM 호출. 실패하면 조용히 None을 돌려주고 템플릿으로 내려간다.

    발표 안정성이 최우선이라 기본값은 비활성이다. PD_LLM_ENABLED=1일 때만 켜진다.
    실제 호출 코드는 키·비용 결정(PRD §19, D-7)이 끝난 뒤에 채운다.
    """
    return None
