"""P2 기준선 회귀 테스트 — 이 테스트가 P3 산출물의 핵심 계약이다.

P2가 만든 tests/persona_fixtures.json의 expected 값과 P3 엔진 결과가 정확히 일치해야 한다.
어긋나면 둘 중 하나가 틀린 것이고, 어느 쪽이든 발표 전에 잡아야 한다.

문항·가중치를 바꾸면 이 테스트가 깨진다. 그게 목적이다.
깨진 걸 확인하고 P2가 기준선을 갱신한 뒤에야 변경이 확정된다.
"""
import json

import pytest

from p3.domain import branching, profile as profile_mod, scoring

FIXTURES = json.load(
    open(
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "fixtures"
        / "persona_fixtures.json",
        encoding="utf-8",
    )
)

CASES = [
    (p["id"], stage, p) for p in FIXTURES["personas"] for stage in ("core", "deep")
]


def _answers(persona, stage):
    a = dict(persona["core_answers"])
    if stage == "deep":
        a.update(persona["deep_answers"])
    return a


@pytest.mark.parametrize("pid,stage,persona", CASES, ids=[f"{c[0]}-{c[1]}" for c in CASES])
def test_full_ranking_matches_baseline(pid, stage, persona):
    ranked = scoring.annotate_bands(scoring.rank(profile_mod.build_profile(_answers(persona, stage))))
    assert [r["job_family_id"] for r in ranked] == persona["expected"][stage]["full_ranking"]


@pytest.mark.parametrize("pid,stage,persona", CASES, ids=[f"{c[0]}-{c[1]}" for c in CASES])
def test_top3_scores_and_bands_match_baseline(pid, stage, persona):
    ranked = scoring.annotate_bands(scoring.rank(profile_mod.build_profile(_answers(persona, stage))))
    for expected, got in zip(persona["expected"][stage]["top3"], ranked[:3]):
        assert got["job_family_id"] == expected["job_family_id"]
        assert got["total"] == pytest.approx(expected["total"], abs=0.05)
        assert got["band"] == expected["band"]


@pytest.mark.parametrize("pid,stage,persona", CASES, ids=[f"{c[0]}-{c[1]}" for c in CASES])
def test_confidence_matches_baseline(pid, stage, persona):
    prof = profile_mod.build_profile(_answers(persona, stage))
    assert prof["confidence"] == persona["expected"][stage]["confidence"]


@pytest.mark.parametrize("persona", FIXTURES["personas"], ids=[p["id"] for p in FIXTURES["personas"]])
def test_branch_clusters_match_baseline(persona):
    assert branching.selected_clusters(persona["core_answers"]) == persona["expected_clusters"]


def test_same_input_gives_same_output():
    """재현성. 같은 응답을 열 번 돌려도 결과가 흔들리지 않아야 한다."""
    persona = FIXTURES["personas"][0]
    answers = _answers(persona, "deep")
    runs = [
        [(r["job_family_id"], r["total"]) for r in scoring.rank(profile_mod.build_profile(answers))]
        for _ in range(10)
    ]
    assert all(run == runs[0] for run in runs)
