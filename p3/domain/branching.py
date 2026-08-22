"""문항 노출·분기 규칙. 순수 함수만 둔다.

분기의 계약 (P2 questions.json의 branching_rule):
  - 코어 SJT 4문항의 선택지가 4개 클러스터에 +1씩 누적된다
  - 누적 상위 2개 클러스터를 고른다. 동점이면 먼저 선택한 클러스터를 우선한다
  - 선택된 클러스터별 후속 문항 3개 중 앞의 2개를 노출한다 (총 4문항)
  - 어떤 경로를 타도 심화 문항 수는 같다
"""
from p3.domain import content

DEEP_FOLLOWUP_PER_CLUSTER = 2
DEEP_CLUSTER_COUNT = 2


def cluster_tally(answers):
    """코어 SJT 응답에서 클러스터 누적과 선택 순서를 함께 낸다.

    동점 처리에 '먼저 고른 쪽'이 필요하므로 순서를 버리면 안 된다.
    dict는 파이썬 3.7+에서 삽입 순서를 유지하지만, 그것에 기대지 않고
    first_seen을 명시적으로 기록한다.
    """
    qmap = content.question_map()
    counts = {}
    first_seen = {}

    core_sjt = [q for q in content.core_questions() if q["module"] == "sjt"]
    for order, q in enumerate(core_sjt):
        chosen = answers.get(q["question_id"])
        if chosen is None:
            continue
        opt = next((o for o in q["options"] if o["option_id"] == chosen), None)
        if opt is None:
            raise ValueError(f"{q['question_id']}에 없는 선택지입니다: {chosen}")
        cl = opt["cluster"]
        counts[cl] = counts.get(cl, 0) + 1
        first_seen.setdefault(cl, order)

    return counts, first_seen


def selected_clusters(answers):
    """누적 상위 2개 클러스터. 동점은 먼저 고른 쪽이 이긴다.

    엣지 케이스: SJT 4문항을 모두 같은 클러스터로 답하면 득표 클러스터가 하나뿐이라
    후속 문항이 2개밖에 안 나온다. 그러면 일관되게 답한 사용자가 우유부단한 사용자보다
    역량 신호를 적게 남기게 되는데, 이건 거꾸로다.
    그래서 부족한 자리는 questions.json의 클러스터 정의 순서대로 채운다.
    득표가 없는 클러스터를 넣는 것이라 '대조 확인' 성격이며, 완전히 결정론적이다.
    """
    counts, first_seen = cluster_tally(answers)
    if not counts:
        return []
    ranked = sorted(counts, key=lambda c: (-counts[c], first_seen[c]))

    if len(ranked) < DEEP_CLUSTER_COUNT:
        for name in content.questions()["clusters"]:
            if name not in ranked:
                ranked.append(name)
            if len(ranked) == DEEP_CLUSTER_COUNT:
                break

    return ranked[:DEEP_CLUSTER_COUNT]


def deep_followups(answers):
    """선택된 클러스터에 연결된 후속 문항을 노출 순서대로 반환한다."""
    clusters = selected_clusters(answers)
    pool = content.deep_questions("sjt_followup")

    out = []
    for cl in clusters:
        linked = [q for q in pool if q["cluster"] == cl]
        out.extend(linked[:DEEP_FOLLOWUP_PER_CLUSTER])
    return out


def deep_questions_for(answers):
    """심화 단계에서 보여줄 전체 문항. 후속 분기 → 역량 자기평가 → 현실 조건 순."""
    return (
        deep_followups(answers)
        + content.deep_questions("competency_self")
        + content.deep_questions("context")
    )


def is_core_complete(answers):
    """코어 필수 문항이 모두 채워졌는지. 결과 계산 전 게이트."""
    return all(q["question_id"] in answers for q in content.core_questions())


def missing_core(answers):
    return [q["question_id"] for q in content.core_questions() if q["question_id"] not in answers]
