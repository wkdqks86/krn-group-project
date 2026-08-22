"""엔진 통합 테스트 + API 장애 시나리오.

발표 게이트가 여기에 걸려 있다. PRD §16 D-9 게이트: "API 장애에도 결과/상세가 정상".
"""
import json

import pytest

from p3 import engine
from p3.db import repository as repo
from p3.services import work24


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    engine.bootstrap(path)
    work24.clear_cache()
    return path


PERSONA = json.load(
    open(
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "fixtures"
        / "persona_fixtures.json",
        encoding="utf-8",
    )
)["personas"][0]


def _run_core(db):
    sid = engine.start_session(db_path=db)
    for qid, val in PERSONA["core_answers"].items():
        engine.answer(sid, qid, val, db_path=db)
    return sid


def test_seed_is_idempotent(db):
    first = engine.bootstrap(db)
    second = engine.bootstrap(db)
    assert first == second
    with repo.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) c FROM job_families").fetchone()["c"] == 10


def test_core_flow_produces_three_cards(db):
    sid = _run_core(db)
    assert engine.core_progress(sid, db_path=db)["complete"]
    result = engine.compute(sid, "core", db_path=db)
    assert len(result["top"]) == 3
    assert result["confidence"] == "low"
    assert result["deep_invite"], "코어 결과에는 심화 권유 문구가 있어야 한다"


def test_result_is_persisted_with_versions(db):
    sid = _run_core(db)
    engine.compute(sid, "core", db_path=db)
    saved = repo.load_recommendations(sid, "core", db_path=db)
    assert len(saved) == 10
    v = engine.versions()
    assert saved[0]["engine_version"] == v["engine_version"]
    assert saved[0]["job_profile_version"] == v["job_profile_version"]
    assert saved[0]["question_version"] == v["question_version"]


def test_recompute_is_stable(db):
    """같은 응답으로 다시 계산해도 결과가 같고 행이 중복되지 않는다."""
    sid = _run_core(db)
    first = engine.compute(sid, "core", db_path=db)
    second = engine.compute(sid, "core", db_path=db)
    assert [r["job_family_id"] for r in first["all"]] == [r["job_family_id"] for r in second["all"]]
    assert len(repo.load_recommendations(sid, "core", db_path=db)) == 10


def test_core_result_ignores_deep_answers(db):
    """1차 결과는 코어 문항만으로 낸다. 심화 응답이 있어도 섞이면 안 된다."""
    sid = _run_core(db)
    core_only = engine.compute(sid, "core", db_path=db)
    for qid, val in PERSONA["deep_answers"].items():
        engine.answer(sid, qid, val, db_path=db)
    core_again = engine.compute(sid, "core", db_path=db)
    assert core_only["all"][0]["total"] == core_again["all"][0]["total"]


def test_deep_flow_and_comparison(db):
    sid = _run_core(db)
    engine.compute(sid, "core", db_path=db)

    deep = engine.get_deep_questions(sid, db_path=db)
    assert deep["clusters"] == PERSONA["expected_clusters"]

    for qid, val in PERSONA["deep_answers"].items():
        engine.answer(sid, qid, val, db_path=db)
    result = engine.compute(sid, "deep", db_path=db)
    assert result["confidence"] == "high"

    diff = engine.compare_stages(sid, db_path=db)
    assert diff is not None and diff["message"]


def test_compute_blocked_until_core_complete(db):
    sid = engine.start_session(db_path=db)
    engine.answer(sid, "Q01", 3, db_path=db)
    with pytest.raises(ValueError, match="코어 문항이 아직 남았습니다"):
        engine.compute(sid, "core", db_path=db)


def test_prior_test_does_not_affect_score(db):
    """MBTI는 점수 계산에 반영하지 않는다 (PRD §19 확정)."""
    sid = _run_core(db)
    before = engine.compute(sid, "core", db_path=db)
    engine.save_prior_test(sid, mbti="INTJ", enneagram="5", db_path=db)
    after = engine.compute(sid, "core", db_path=db)
    assert [r["total"] for r in before["all"]] == [r["total"] for r in after["all"]]


# --- API 장애 -------------------------------------------------------------


def test_detail_works_without_api_key(db, monkeypatch):
    """키가 없으면 호출조차 하지 않고 스냅샷으로 완결된다."""
    monkeypatch.setattr(work24, "work24_enabled", lambda: False)
    detail = engine.get_family_detail("J01", db_path=db)
    assert detail["occupations"], "스냅샷만으로도 연관 직업이 나와야 한다"
    assert all(o["source_label"] for o in detail["occupations"]), "출처 없이 화면에 올리지 않는다"
    assert detail["notice"] is None, "키가 없는 건 장애가 아니므로 오류 문구를 띄우지 않는다"


def _inject_failing_requests(monkeypatch, exc):
    """work24가 지연 import 하는 requests를 가짜로 바꿔 끼운다.

    requests가 설치돼 있지 않은 환경에서도 이 테스트가 돌아야 하므로
    sys.modules에 직접 주입한다.
    """
    import sys
    import types

    fake = types.ModuleType("requests")

    def boom(*a, **kw):
        raise exc

    fake.get = boom
    monkeypatch.setitem(sys.modules, "requests", fake)


@pytest.mark.parametrize(
    "exc",
    [ConnectionError("네트워크 끊김"), TimeoutError("응답 없음"), ValueError("XML 파싱 실패")],
    ids=["connection", "timeout", "parse"],
)
def test_detail_survives_api_exception(db, monkeypatch, exc):
    """API가 어떤 예외를 던져도 상세 화면은 그려진다. PRD §16 D-9 게이트."""
    monkeypatch.setattr(work24, "work24_enabled", lambda: True)
    monkeypatch.setattr("p3.config.WORK24_API_KEY", "dummy")
    monkeypatch.setattr(work24, "WORK24_API_KEY", "dummy")
    _inject_failing_requests(monkeypatch, exc)

    detail = engine.get_family_detail("J02", db_path=db)
    assert detail["occupations"], "API가 죽어도 스냅샷으로 연관 직업이 나와야 한다"
    assert detail["degraded"] is True
    assert detail["notice"], "장애 시에는 안내 문구를 보여준다"
    assert all(o["from_api"] is False for o in detail["occupations"])

    with repo.connect(db) as conn:
        statuses = [r["status"] for r in conn.execute("SELECT status FROM api_fetch_logs").fetchall()]
    assert any(st.startswith("error:") for st in statuses), "실패도 기록해야 원인을 찾을 수 있다"


def test_full_flow_works_with_api_down(db, monkeypatch):
    """네트워크가 완전히 죽은 상태로 진단 시작부터 상세까지 끝까지 간다. 리허설 시나리오."""
    monkeypatch.setattr(work24, "work24_enabled", lambda: True)
    monkeypatch.setattr(work24, "WORK24_API_KEY", "dummy")
    _inject_failing_requests(monkeypatch, ConnectionError("오프라인"))

    sid = _run_core(db)
    result = engine.compute(sid, "core", db_path=db)
    assert len(result["top"]) == 3

    for card in result["top"]:
        detail = engine.get_family_detail(card["job_family_id"], sid, db_path=db)
        assert detail["occupations"]


def test_api_failure_is_logged_without_secrets(db, monkeypatch):
    """인증키가 api_fetch_logs로 새면 안 된다. 실제로 키를 들고 호출하는 경로를 태운다."""
    monkeypatch.setattr(work24, "work24_enabled", lambda: True)
    monkeypatch.setattr(work24, "WORK24_API_KEY", "SECRET-KEY-123")
    _inject_failing_requests(monkeypatch, ConnectionError("끊김"))

    assert work24.fetch_job_info("데이터", db_path=db) is None
    with repo.connect(db) as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM api_fetch_logs").fetchall()]
    assert rows, "호출 결과는 반드시 기록한다"
    blob = json.dumps(rows, ensure_ascii=False)
    assert "SECRET-KEY-123" not in blob, "인증키가 로그에 새면 안 된다"


def test_unknown_family_raises(db):
    with pytest.raises(ValueError, match="없는 직군"):
        engine.get_family_detail("J99", db_path=db)


def test_feedback_does_not_touch_scores(db):
    sid = _run_core(db)
    before = engine.compute(sid, "core", db_path=db)
    engine.save_feedback(sid, "도움 됐어요", "근거가 이해됐어요", db_path=db)
    after = repo.load_recommendations(sid, "core", db_path=db)
    assert [r["total"] for r in before["all"]] == [r["total"] for r in after]
