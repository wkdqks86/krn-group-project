"""분기 규칙과 프로파일 계산 단위 테스트."""
import pytest

from p3.domain import branching, content, profile as profile_mod

CORE_SJT = ["Q11", "Q12", "Q13", "Q14"]


def _core_answers(sjt_options):
    """코어 14문항을 채운다. Big Five는 전부 3(보통), RIASEC은 A 선택."""
    a = {f"Q0{i}": 3 for i in range(1, 7)}
    a.update({"Q07": "Q07A", "Q08": "Q08A", "Q09": "Q09A", "Q10": "Q10A"})
    a.update(dict(zip(CORE_SJT, sjt_options)))
    return a


def test_every_path_yields_exactly_four_followups():
    """어떤 분기를 타도 후속 문항 수가 같아야 소요 시간이 예측된다.

    한 클러스터에 4표를 몰아준 사용자도 4문항을 받아야 한다.
    안 그러면 일관되게 답한 사람이 우유부단한 사람보다 역량 신호를 적게 남긴다.
    """
    for suffix in "ABCD":
        answers = _core_answers([f"{q}{suffix}" for q in CORE_SJT])
        assert len(branching.selected_clusters(answers)) == 2, suffix
        assert len(branching.deep_followups(answers)) == 4, suffix


def test_all_split_paths_yield_four_followups():
    """4표가 4개 클러스터로 흩어져도, 2:2로 갈려도 항상 4문항."""
    import itertools

    for combo in itertools.product("ABCD", repeat=4):
        answers = _core_answers([f"{q}{c}" for q, c in zip(CORE_SJT, combo)])
        assert len(branching.deep_followups(answers)) == 4, combo


def test_two_clusters_selected_when_split():
    answers = _core_answers(["Q11A", "Q12A", "Q13D", "Q14D"])
    assert branching.selected_clusters(answers) == ["ANALYZE", "PERSUADE"]
    assert len(branching.deep_followups(answers)) == 4


def test_tie_prefers_first_chosen_cluster():
    """동점이면 먼저 고른 클러스터가 이긴다. 순서를 버리면 결과가 흔들린다."""
    a = _core_answers(["Q11C", "Q12A", "Q13A", "Q14C"])  # ORCHESTRATE 먼저, 각 2표
    assert branching.selected_clusters(a)[0] == "ORCHESTRATE"
    b = _core_answers(["Q11A", "Q12C", "Q13C", "Q14A"])  # ANALYZE 먼저, 각 2표
    assert branching.selected_clusters(b)[0] == "ANALYZE"


def test_followups_belong_to_selected_clusters():
    answers = _core_answers(["Q11B", "Q12B", "Q13C", "Q14C"])
    selected = set(branching.selected_clusters(answers))
    assert {q["cluster"] for q in branching.deep_followups(answers)} <= selected


def test_core_completeness_gate():
    answers = _core_answers(["Q11A", "Q12A", "Q13A", "Q14A"])
    assert branching.is_core_complete(answers)
    answers.pop("Q07")
    assert not branching.is_core_complete(answers)
    assert branching.missing_core(answers) == ["Q07"]


# --- 프로파일 ---------------------------------------------------------------


def test_reverse_item_is_flipped():
    """Q05는 역문항이다. 5점을 주면 정서적 안정성은 낮게 나와야 한다."""
    high = profile_mod.build_profile({"Q05": 1})["big5"]["ES"]
    low = profile_mod.build_profile({"Q05": 5})["big5"]["ES"]
    assert high == 100.0 and low == 0.0


def test_unasked_axis_is_neutral_not_zero():
    """물어보지 않은 축은 '낮다'가 아니라 '모른다'다. 0을 주면 직군이 구조적으로 밀린다."""
    prof = profile_mod.build_profile({"Q01": 3})
    assert prof["riasec"]["R"] == profile_mod.NEUTRAL


def test_axis_max_is_dynamic_not_fixed():
    """축별 최대 획득 점수가 다르므로 분모를 고정하면 눈금이 달라진다."""
    core = [q for q in content.core_questions() if q["module"] in ("riasec", "sjt")]
    maxes = profile_mod._axis_max(core, "riasec")
    assert len(set(maxes.values())) > 1, "축별 최대치가 모두 같다면 이 규칙은 불필요하다"
    assert maxes["R"] < maxes["I"]


def test_competency_switches_to_60_40_with_self_assessment():
    base = _core_answers(["Q11A", "Q12A", "Q13A", "Q14A"])
    assert profile_mod.build_profile(base)["confidence"] == "low"

    base.update({f"D-SC-{i}": 1 for i in range(1, 6)})  # 자기평가 최저 = 0점
    deep = profile_mod.build_profile(base)
    assert deep["confidence"] == "high"

    # 계약 그대로: 자기평가 60% + 행동신호 40%
    for axis, value in deep["competency"].items():
        expected = round(0.6 * 0.0 + 0.4 * deep["competency_behavior"][axis], 1)
        assert value == pytest.approx(expected, abs=0.05), axis

    # 자기평가가 0이므로 어느 축도 행동신호보다 높을 수 없다
    assert all(
        deep["competency"][a] <= deep["competency_behavior"][a] for a in deep["competency"]
    )


def test_unknown_question_id_raises():
    with pytest.raises(ValueError, match="문항 정의에 없는"):
        profile_mod.build_profile({"NOPE": 3})


def test_unknown_option_id_raises():
    with pytest.raises(ValueError, match="없는 선택지"):
        profile_mod.build_profile({"Q07": "Q07Z"})


def test_likert_out_of_range_raises():
    with pytest.raises(ValueError, match="5점 척도"):
        profile_mod.build_profile({"Q01": 9})
