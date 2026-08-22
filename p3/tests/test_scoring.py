"""점수 계산 단위 테스트 — 계약이 깨지면 여기서 먼저 걸린다."""
import pytest

from p3.domain import content, profile as profile_mod, scoring


def _flat_profile(value=50.0):
    ax = content.axes()
    return {
        "big5": {a: value for a in ax["big5"]},
        "riasec": {a: value for a in ax["riasec"]},
        "competency": {a: value for a in ax["competency"]},
        "competency_behavior": {a: value for a in ax["competency"]},
        "environment": None,
        "confidence": "low",
    }


def test_weights_sum_to_one():
    """가중치 합이 1.00이 아니면 group_fit이 왜곡된다. PRD 부록 A가 0.80이었던 문제."""
    for fam in content.job_profiles()["job_families"]:
        for key in ("competency_weight", "riasec_weight", "big5_weight"):
            assert sum(fam[key].values()) == pytest.approx(1.0, abs=1e-9), (fam["job_family_id"], key)


def test_ten_job_families():
    """P2 job_profiles.json 기준 10개 대분류(원안 8 + 제조·보건)."""
    ids = [f["job_family_id"] for f in content.job_profiles()["job_families"]]
    assert ids == ["J01", "J02", "J03", "J04", "J05", "J06", "J07", "J08", "J09", "J10"]


def test_perfect_match_scores_100():
    """사용자 벡터가 직군 요구값과 같으면 그 그룹 적합도는 100이다."""
    fam = content.job_profiles()["job_families"][0]
    prof = _flat_profile()
    prof["riasec"] = dict(fam["riasec_target"])
    prof["competency"] = dict(fam["competency_target"])
    prof["big5"] = dict(fam["big5_target"])
    result = scoring.score_family(prof, fam)
    assert result["total"] == pytest.approx(100.0, abs=0.05)


def test_element_fit_never_negative():
    """격차가 100을 넘어도 음수가 되면 안 된다."""
    assert scoring._element_fit(0, 100) == 0.0
    assert scoring._element_fit(1, 5, is_environment=True) == 0.0


def test_core_weights_sum_to_one():
    """ContextFit이 없을 때 나머지를 재정규화한 값의 합이 1이어야 한다."""
    assert sum(scoring.CORE_WEIGHTS.values()) == pytest.approx(1.0)
    assert sum(scoring.FULL_WEIGHTS.values()) == pytest.approx(1.0)


def test_context_absent_returns_none():
    fam = content.job_profiles()["job_families"][0]
    assert scoring.context_fit(_flat_profile(), fam) is None


def test_context_present_shifts_total():
    """현실 조건을 넣으면 총점 구성이 달라진다."""
    fam = content.job_profiles()["job_families"][0]
    prof = _flat_profile()
    without = scoring.score_family(prof, fam)
    prof["environment"] = dict(fam["environment"])
    with_ctx = scoring.score_family(prof, fam)
    assert without["component_scores"]["context"] is None
    assert with_ctx["component_scores"]["context"] is not None


def test_tie_break_is_total_order():
    """동점이어도 직군 ID까지 내려가면 순서가 절대 흔들리지 않는다."""
    ranked = scoring.rank(_flat_profile())
    totals = [r["total"] for r in ranked]
    assert totals == sorted(totals, reverse=True)
    assert len({r["job_family_id"] for r in ranked}) == len(ranked)


def test_top3_never_labelled_distant():
    """상단 문구가 '세 갈래'인데 3위에 '거리가 있음'이 붙으면 화면이 자기모순이 된다."""
    ranked = scoring.annotate_bands(scoring.rank(_flat_profile()))
    distant = content.result_copy()["bands"]["levels"][-1]["label"]
    assert all(r["band"] != distant for r in ranked[:3])


def test_top3_never_collapsed():
    ranked = scoring.annotate_bands(scoring.rank(_flat_profile()))
    assert all(not r["collapsed"] for r in ranked[:3])


def test_band_uses_relative_delta():
    """1위와의 차이가 커지면 밴드가 내려가야 한다."""
    levels = content.result_copy()["bands"]["levels"]
    assert scoring.band_for(90.0, 90.0, 5)["label"] == levels[0]["label"]
    assert scoring.band_for(60.0, 90.0, 5)["label"] == levels[-1]["label"]
