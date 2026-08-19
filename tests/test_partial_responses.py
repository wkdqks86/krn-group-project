"""진단을 끝까지 답하지 않은 상태에서도 엔진이 죽지 않아야 한다.

지금 앱은 전부 답한 뒤에만 계산을 부르지만, 중간 저장·미리보기·뒤로가기를 넣으면
부분 응답 상태로 호출된다. 그때 예외가 나면 화면이 통째로 깨진다.
"""

import json
from pathlib import Path

import pytest

from domain.branching import build_user_profile
from domain.scoring import AXES, build_user_vector, rank_job_families

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = json.loads((ROOT / "data" / "questions.json").read_text(encoding="utf-8"))
JOB_PROFILES = json.loads((ROOT / "data" / "job_profiles.json").read_text(encoding="utf-8"))

NEUTRAL = 50.0


def test_no_responses_at_all():
    """아무것도 안 답한 상태. 모든 축이 중립 50이어야 한다."""
    vector, _clusters = build_user_profile(QUESTIONS, {})
    assert set(vector) == set(AXES)
    for axis, value in vector.items():
        assert value == pytest.approx(NEUTRAL), f"{axis}가 중립이 아닙니다: {value}"


def test_partial_likert_only():
    """리커트 몇 개만 답한 상태에서도 예외 없이 벡터가 나온다."""
    vector, _clusters = build_user_profile(QUESTIONS, {"R1": 5, "R2": 5, "I1": 1})
    assert vector["R"] == pytest.approx(100.0)
    # 답하지 않은 축은 중립
    assert vector["S"] == pytest.approx(NEUTRAL)
    assert vector["self_management_execution"] == pytest.approx(NEUTRAL)


def test_partial_response_can_still_be_ranked():
    """부분 응답으로도 순위 계산까지 끝까지 간다."""
    vector, _clusters = build_user_profile(QUESTIONS, {"A1": 5, "A2": 5})
    ranked = rank_job_families(vector, JOB_PROFILES["job_families"], top_n=3)
    assert len(ranked) == 3
    assert all(0 <= item["total"] <= 100 for item in ranked)


def test_unanswered_axis_defaults_to_neutral():
    """빈 리스트가 들어와도 기본값 3점이 적용되어야 한다.

    이 PR이 고친 지점이다. 예전에는 여기서 ValueError가 났다.
    """
    empty = {axis: [] for axis in AXES}
    vector = build_user_vector(empty, {axis: None for axis in AXES})
    assert all(value == pytest.approx(NEUTRAL) for value in vector.values())


def test_missing_axis_key_also_defaults_to_neutral():
    """키 자체가 없는 경우도 같아야 한다."""
    vector = build_user_vector({}, {})
    assert all(value == pytest.approx(NEUTRAL) for value in vector.values())


def test_answered_axis_is_not_overwritten_by_default():
    """중립 처리가 실제 응답을 덮어쓰면 안 된다."""
    partial = {axis: [] for axis in AXES}
    partial["logical"] = [5.0, 5.0]
    vector = build_user_vector(partial, {axis: None for axis in AXES})
    assert vector["logical"] == pytest.approx(100.0)
    assert vector["persistence"] == pytest.approx(NEUTRAL)


def test_sjt_without_likert_does_not_crash():
    """SJT만 답하고 리커트를 건너뛴 경우."""
    vector, clusters = build_user_profile(
        QUESTIONS, {"SJT1": "SJT1_A", "SJT2": "SJT2_A", "SJT3": "SJT3_A", "SJT4": "SJT4_A"}
    )
    assert len(clusters) == 2
    assert all(0 <= value <= 100 for value in vector.values())
