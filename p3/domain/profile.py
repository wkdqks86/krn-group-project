"""응답 → 사용자 프로파일. 순수 함수만 둔다.

정규화 계약은 P2 questions.json의 normalization 블록이 원본이고, 여기서는 그대로 구현한다.
핵심은 축별 분모를 고정하지 않는다는 것이다. 코어 14문항 기준 축별 최대 획득 점수가
I=11, E=11, C=9, S=9, A=8, R=7로 불균등해서, 고정 분모를 쓰면 축마다 눈금이 다른 자로 재게 된다.
"""
from collections import defaultdict

from p3.domain import content

SCORE_FLOOR = 30.0
SCORE_SPAN = 70.0
NEUTRAL = 50.0
SELF_ASSESS_WEIGHT = 0.6
BEHAVIOR_WEIGHT = 0.4


def _likert_to_100(value, reverse=False):
    if not 1 <= value <= 5:
        raise ValueError(f"5점 척도 범위를 벗어난 값입니다: {value}")
    return (5 - value) / 4 * 100 if reverse else (value - 1) / 4 * 100


def _axis_max(shown, group):
    """노출된 문항 기준으로 축별 최대 획득 가능 점수를 낸다.

    한 문항에서는 선택지 하나만 고를 수 있으므로, 문항마다 그 축의 최댓값을 취해 합산한다.
    """
    total = defaultdict(int)
    for q in shown:
        best = defaultdict(int)
        for opt in q.get("options", []):
            for axis, val in opt.get("score_map", {}).get(group, {}).items():
                best[axis] = max(best[axis], val)
        for axis, val in best.items():
            total[axis] += val
    return total


def _normalize(raw, axis_max, axis_names):
    out = {}
    for axis in axis_names:
        m = axis_max.get(axis, 0)
        # 그 축을 한 번도 물어보지 않았다면 '낮다'가 아니라 '모른다'이므로 중립을 준다
        out[axis] = NEUTRAL if m == 0 else round(SCORE_FLOOR + (raw.get(axis, 0) / m) * SCORE_SPAN, 1)
    return out


def _shown_questions(answers):
    qmap = content.question_map()
    unknown = [qid for qid in answers if qid not in qmap]
    if unknown:
        raise ValueError(f"문항 정의에 없는 응답입니다: {unknown}")
    return [qmap[qid] for qid in answers]


def build_profile(answers):
    """answers: {question_id: value}

    likert5 → int 1~5, single_choice → option_id, C06 → {axis: 1~5}
    """
    shown = _shown_questions(answers)
    ax = content.axes()

    # --- Big Five: 축별 문항 점수의 산술평균 ---
    bucket = defaultdict(list)
    for q in shown:
        if q["module"] != "big5":
            continue
        bucket[q["axis"]].append(_likert_to_100(answers[q["question_id"]], q["reverse"]))
    big5 = {a: round(sum(v) / len(v), 1) for a, v in bucket.items()}
    for a in ax["big5"]:
        big5.setdefault(a, NEUTRAL)

    # --- RIASEC / 역량 행동신호: 선택지 점수 누계 ---
    signal_qs = [q for q in shown if q["module"] in ("riasec", "sjt", "sjt_followup")]
    riasec_raw, comp_raw = defaultdict(int), defaultdict(int)
    for q in signal_qs:
        chosen = answers[q["question_id"]]
        opt = next((o for o in q["options"] if o["option_id"] == chosen), None)
        if opt is None:
            raise ValueError(f"{q['question_id']}에 없는 선택지입니다: {chosen}")
        for axis, val in opt["score_map"].get("riasec", {}).items():
            riasec_raw[axis] += val
        for axis, val in opt["score_map"].get("competency", {}).items():
            comp_raw[axis] += val

    riasec = _normalize(riasec_raw, _axis_max(signal_qs, "riasec"), ax["riasec"])

    behavior_qs = [q for q in signal_qs if q["module"] != "riasec"]
    behavior = _normalize(comp_raw, _axis_max(behavior_qs, "competency"), ax["competency"])

    # --- 역량: 자기평가가 있으면 60/40, 없으면 행동신호 100% ---
    self_scores = {
        q["competency"]: _likert_to_100(answers[q["question_id"]])
        for q in shown
        if q["module"] == "competency_self"
    }
    if self_scores:
        competency = {
            a: round(SELF_ASSESS_WEIGHT * self_scores.get(a, behavior[a]) + BEHAVIOR_WEIGHT * behavior[a], 1)
            for a in ax["competency"]
        }
        confidence = "high"
    else:
        competency = dict(behavior)
        confidence = "low"

    environment = answers.get("C06")
    if environment is not None:
        missing = [a for a in ax["environment"] if a not in environment]
        if missing:
            raise ValueError(f"업무환경 입력에 빠진 축이 있습니다: {missing}")

    return {
        "big5": big5,
        "riasec": riasec,
        "competency": competency,
        "competency_behavior": behavior,
        "environment": environment,
        "confidence": confidence,
    }
