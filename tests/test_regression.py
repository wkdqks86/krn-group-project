"""대표 사용자 결과 회귀 테스트.

Git 가이드 §5: "tests/ — 대표 사용자 결과 회귀 테스트 (엔진 담당, PR마다 실행)"
Git 가이드 §5: "점수 계산에 영향을 주는 데이터 변경 PR에는 대표 사용자 3명의 TOP 3가
              어떻게 바뀌었는지를 적는다"

이 테스트가 그 확인을 자동화한다.

문항·가중치·계산식을 바꾸면 이 테스트가 깨진다. 그게 목적이다.
깨진 걸 보고 "의도한 변경이 맞다"고 판단했을 때만 기준선을 다시 만든다.

    python -m pytest tests/test_regression.py -q     확인
    python tests/regenerate_baseline.py              의도한 변경 후 기준선 갱신

기준선은 tests/fixtures/persona_responses.json의 expected에 들어 있다.
값을 손으로 고치지 않는다.
"""

import json
from pathlib import Path

import pytest

from domain.branching import build_user_profile, visible_question_queue
from domain.scoring import AXES, rank_job_families

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "persona_responses.json").read_text(encoding="utf-8"))
PERSONAS = FIXTURE["personas"]
IDS = [p["id"] for p in PERSONAS]


def load_json(name: str):
    return json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))


QUESTIONS = load_json("questions.json")
JOB_PROFILES = load_json("job_profiles.json")


def run_engine(responses):
    user_vector, clusters = build_user_profile(QUESTIONS, responses)
    ranked = rank_job_families(user_vector, JOB_PROFILES["job_families"], top_n=8)
    return user_vector, clusters, ranked


# --- 결과 고정 --------------------------------------------------------------


@pytest.mark.parametrize("persona", PERSONAS, ids=IDS)
def test_top3_is_unchanged(persona):
    """TOP 3 직군과 순서가 기준선과 같아야 한다. 가장 먼저 보는 신호다."""
    _vector, _clusters, ranked = run_engine(persona["responses"])
    got = [item["job_family_id"] for item in ranked[:3]]
    expected = [item["job_family_id"] for item in persona["expected"]["ranking"][:3]]
    assert got == expected, (
        f"{persona['name']}의 TOP 3가 바뀌었습니다.\n"
        f"  기준선: {expected}\n  현재:   {got}\n"
        f"의도한 변경이면 python tests/regenerate_baseline.py 로 기준선을 갱신하고 PR에 이유를 적어 주세요."
    )


@pytest.mark.parametrize("persona", PERSONAS, ids=IDS)
def test_full_ranking_is_unchanged(persona):
    """8개 직군 전체 순서. 하위권이 흔들려도 알아차릴 수 있게 한다."""
    _vector, _clusters, ranked = run_engine(persona["responses"])
    got = [item["job_family_id"] for item in ranked]
    expected = [item["job_family_id"] for item in persona["expected"]["ranking"]]
    assert got == expected


@pytest.mark.parametrize("persona", PERSONAS, ids=IDS)
def test_scores_are_unchanged(persona):
    """점수까지 고정한다. 순위가 같아도 점수가 흔들리면 가중치가 바뀐 것이다."""
    _vector, _clusters, ranked = run_engine(persona["responses"])
    for expected, got in zip(persona["expected"]["ranking"], ranked):
        assert got["job_family_id"] == expected["job_family_id"]
        assert got["total"] == pytest.approx(expected["total"], abs=0.05), (
            f"{persona['name']} / {expected['name']}의 적합도가 "
            f"{expected['total']} → {got['total']} 로 바뀌었습니다."
        )
        assert got["band"] == expected["band"]


@pytest.mark.parametrize("persona", PERSONAS, ids=IDS)
def test_user_vector_is_unchanged(persona):
    """12축 사용자 벡터. 문항이나 정규화가 바뀌면 여기서 먼저 걸린다."""
    vector, _clusters, _ranked = run_engine(persona["responses"])
    for axis, expected in persona["expected"]["user_vector"].items():
        assert vector[axis] == pytest.approx(expected, abs=0.05), f"{persona['name']} / {axis}"


# --- 분기 ------------------------------------------------------------------


@pytest.mark.parametrize("persona", PERSONAS, ids=IDS)
def test_clusters_are_unchanged(persona):
    _vector, clusters, _ranked = run_engine(persona["responses"])
    assert clusters == persona["expected"]["clusters"]


@pytest.mark.parametrize("persona", PERSONAS, ids=IDS)
def test_every_visible_question_is_answered(persona):
    """픽스처가 노출 문항을 빠짐없이 답했는지 확인한다.

    문항이 추가됐는데 픽스처를 안 고치면 여기서 걸린다.
    """
    queue = visible_question_queue(QUESTIONS, persona["responses"])
    missing = [item["question_id"] for item in queue if item["question_id"] not in persona["responses"]]
    assert missing == [], f"{persona['name']} 픽스처에 답이 빠진 문항: {missing}"


@pytest.mark.parametrize("persona", PERSONAS, ids=IDS)
def test_question_count_is_stable(persona):
    """어떤 경로를 타도 노출 문항 수가 같아야 소요 시간이 예측된다."""
    queue = visible_question_queue(QUESTIONS, persona["responses"])
    assert len(queue) == persona["expected"]["visible_question_count"]


def test_all_personas_see_the_same_number_of_questions():
    counts = {p["id"]: p["expected"]["visible_question_count"] for p in PERSONAS}
    assert len(set(counts.values())) == 1, f"경로마다 문항 수가 다릅니다: {counts}"


# --- 재현성 ----------------------------------------------------------------


@pytest.mark.parametrize("persona", PERSONAS, ids=IDS)
def test_same_input_gives_same_output(persona):
    """같은 응답을 열 번 돌려도 결과가 흔들리면 안 된다. PRD의 재현성 요구."""
    runs = [
        [(item["job_family_id"], item["total"]) for item in run_engine(persona["responses"])[2]]
        for _ in range(10)
    ]
    assert all(run == runs[0] for run in runs)


def test_personas_reach_different_top_families():
    """세 사람이 모두 같은 직군을 1위로 받으면 진단이 변별을 못 하는 것이다."""
    tops = {p["id"]: run_engine(p["responses"])[2][0]["job_family_id"] for p in PERSONAS}
    assert len(set(tops.values())) == len(tops), f"1위 직군이 겹칩니다: {tops}"


# --- 데이터 정합성 ----------------------------------------------------------


def test_axis_sets_match_across_files():
    """scoring.AXES, job_profiles.axes, 문항의 axis가 서로 어긋나면 계산이 조용히 틀어진다."""
    assert set(JOB_PROFILES["axes"]) == set(AXES)
    question_axes = {q["axis"] for q in QUESTIONS["questions"] if q.get("axis")}
    assert question_axes <= set(AXES), f"문항에만 있는 축: {question_axes - set(AXES)}"


def test_every_axis_has_at_least_one_likert_question():
    """리커트 문항이 없는 축은 사용자 점수를 만들 수 없다."""
    covered = {
        q["axis"]
        for q in QUESTIONS["questions"]
        if q["type"] == "likert" and q["module"] in {"riasec", "competency"}
    }
    assert set(AXES) - covered == set(), f"리커트 문항이 없는 축: {set(AXES) - covered}"


def _self_ranked_first(job_profiles):
    """각 직군의 요구 벡터를 그대로 가진 사용자에게 그 직군이 1위로 나오는지 조사한다."""
    wins, misses = [], {}
    for family in job_profiles["job_families"]:
        ranked = rank_job_families(dict(family["requirement_vector"]), job_profiles["job_families"], top_n=2)
        if ranked[0]["job_family_id"] == family["job_family_id"]:
            wins.append(family["job_family_id"])
        else:
            misses[family["job_family_id"]] = ranked[0]["job_family_id"]
    return wins, misses


def test_every_job_family_reaches_top2_for_its_own_ideal_user():
    """요구 벡터를 그대로 가진 사용자에게 그 직군이 최소 TOP 2 안에는 들어야 한다.

    여기서 밀리는 직군이 생기면 그 직군은 사실상 추천될 수 없다는 뜻이다.
    """
    for family in JOB_PROFILES["job_families"]:
        ranked = rank_job_families(dict(family["requirement_vector"]), JOB_PROFILES["job_families"], top_n=2)
        top2 = [item["job_family_id"] for item in ranked]
        assert family["job_family_id"] in top2, (
            f"{family['name']}의 요구 벡터를 그대로 가진 사용자에게도 "
            f"그 직군이 TOP 2에 들지 못합니다. 현재 TOP 2: {top2}"
        )


# 2026-08-19 기준 현재 동작을 그대로 적어 둔 것이다. "이래야 한다"가 아니라 "지금 이렇다"이다.
# fit = Σ(w·u·r) / Σ(w·r) 이므로 u == r 이면 점수는 그 직군 요구값의 가중평균이 된다.
# 요구값이 전반적으로 더 높은 직군(J02)이 비슷한 성향의 직군(J03) 이상 사용자에게 더 높게 나올 수 있다.
KNOWN_SELF_WIN_EXCEPTIONS = {"J03": "J02"}


def test_self_win_exceptions_have_not_changed():
    """자기 요구 벡터에서 1위를 놓치는 직군 목록이 바뀌면 알아차린다.

    늘어나면 변별이 나빠진 것이고, 줄어들면 개선된 것이다. 어느 쪽이든 PR에 적어야 한다.
    """
    _wins, misses = _self_ranked_first(JOB_PROFILES)
    assert misses == KNOWN_SELF_WIN_EXCEPTIONS, (
        f"자기 요구 벡터에서 1위를 놓치는 직군이 바뀌었습니다.\n"
        f"  기록된 상태: {KNOWN_SELF_WIN_EXCEPTIONS}\n  현재:        {misses}\n"
        f"의도한 변화면 KNOWN_SELF_WIN_EXCEPTIONS를 갱신하고 PR에 이유를 적어 주세요."
    )
