"""SQLite 접근 계층. SQL은 전부 여기에만 둔다.

domain은 DB를 모르고, DB는 점수 계산을 모른다.
그래서 점수 계산 테스트는 DB 없이 돌고, DB 테스트는 임시 파일로 돈다.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "db" / "schema.sql"
DEFAULT_DB_PATH = ROOT / "potential_discovery.db"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return str(uuid.uuid4())


@contextmanager
def connect(db_path: Path | str | None = None):
    conn = sqlite3.connect(str(db_path or DEFAULT_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema(db_path: Path | str | None = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


# --- 세션 -----------------------------------------------------------------


def create_session(consent_version: str, engine_version: str, db_path=None) -> str:
    user_id, session_id, timestamp = new_id(), new_id(), now()
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO users (user_id, consent_version, created_at) VALUES (?, ?, ?)",
            (user_id, consent_version, timestamp),
        )
        conn.execute(
            "INSERT INTO diagnosis_sessions (session_id, user_id, status, started_at, engine_version)"
            " VALUES (?, ?, 'started', ?, ?)",
            (session_id, user_id, timestamp, engine_version),
        )
    return session_id


def complete_session(session_id: str, db_path=None) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE diagnosis_sessions SET status = 'completed', completed_at = ? WHERE session_id = ?",
            (now(), session_id),
        )


def get_session(session_id: str, db_path=None) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM diagnosis_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    return dict(row) if row else None


# --- 응답 -----------------------------------------------------------------


def save_response(session_id, question_id, value, shown_order=None, db_path=None) -> None:
    """같은 문항에 다시 답하면 덮어쓴다. 사용자가 앞 질문으로 돌아갈 수 있어야 하기 때문이다."""
    option_id = value if isinstance(value, str) else None
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO responses (session_id, question_id, option_id, value_json, shown_order, answered_at)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(session_id, question_id) DO UPDATE SET"
            "   option_id = excluded.option_id,"
            "   value_json = excluded.value_json,"
            "   shown_order = excluded.shown_order,"
            "   answered_at = excluded.answered_at",
            (session_id, question_id, option_id, json.dumps(value, ensure_ascii=False), shown_order, now()),
        )


def save_responses(session_id, responses: dict[str, Any], db_path=None) -> int:
    """st.session_state.responses를 통째로 저장한다. P4가 부르기 편한 형태."""
    for question_id, value in responses.items():
        save_response(session_id, question_id, value, db_path=db_path)
    return len(responses)


def load_responses(session_id, db_path=None) -> dict[str, Any]:
    """{question_id: value} 형태로 되돌린다. 엔진 함수가 바로 먹을 수 있는 모양이다."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT question_id, value_json FROM responses WHERE session_id = ?", (session_id,)
        ).fetchall()
    return {row["question_id"]: json.loads(row["value_json"]) for row in rows}


# --- 프로파일 · 결과 --------------------------------------------------------


def save_profile(session_id, user_vector, clusters, context=None, optional_traits=None, db_path=None) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO profiles (session_id, user_vector_json, clusters_json, context_json,"
            " optional_traits_json, computed_at) VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(session_id) DO UPDATE SET"
            "   user_vector_json = excluded.user_vector_json,"
            "   clusters_json = excluded.clusters_json,"
            "   context_json = excluded.context_json,"
            "   optional_traits_json = excluded.optional_traits_json,"
            "   computed_at = excluded.computed_at",
            (
                session_id,
                json.dumps(user_vector, ensure_ascii=False),
                json.dumps(clusters, ensure_ascii=False),
                json.dumps(context, ensure_ascii=False) if context else None,
                json.dumps(optional_traits, ensure_ascii=False) if optional_traits else None,
                now(),
            ),
        )


def load_profile(session_id, db_path=None) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM profiles WHERE session_id = ?", (session_id,)).fetchone()
    if not row:
        return None
    return {
        "user_vector": json.loads(row["user_vector_json"]),
        "clusters": json.loads(row["clusters_json"]),
        "context": json.loads(row["context_json"]) if row["context_json"] else None,
        "optional_traits": json.loads(row["optional_traits_json"]) if row["optional_traits_json"] else None,
        "computed_at": row["computed_at"],
    }


def save_recommendations(session_id, ranked, versions, db_path=None) -> int:
    """rank_job_families() 결과를 그대로 받는다. 계산에 쓰인 버전을 함께 남긴다."""
    timestamp = now()
    with connect(db_path) as conn:
        conn.execute("DELETE FROM recommendations WHERE session_id = ?", (session_id,))
        conn.executemany(
            "INSERT INTO recommendations (session_id, job_family_id, rank, total, band, close_score,"
            " component_scores_json, cautions_json, engine_version, question_version,"
            " job_profile_version, computed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    session_id,
                    item["job_family_id"],
                    item["rank"],
                    item["total"],
                    item["band"],
                    1 if item.get("close_score") else 0,
                    json.dumps(item.get("component_scores", []), ensure_ascii=False),
                    json.dumps(item.get("cautions", []), ensure_ascii=False),
                    versions["engine_version"],
                    versions["question_version"],
                    versions["job_profile_version"],
                    timestamp,
                )
                for item in ranked
            ],
        )
    return len(ranked)


def load_recommendations(session_id, db_path=None) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM recommendations WHERE session_id = ? ORDER BY rank", (session_id,)
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["component_scores"] = json.loads(item.pop("component_scores_json"))
        item["cautions"] = json.loads(item.pop("cautions_json"))
        item["close_score"] = bool(item["close_score"])
        result.append(item)
    return result


# --- 직업 스냅샷 ------------------------------------------------------------


def load_occupations(job_family_id, db_path=None) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM occupations WHERE job_family_id = ? ORDER BY occupation_id", (job_family_id,)
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["snapshot"] = json.loads(item.pop("snapshot_json") or "{}")
        result.append(item)
    return result


# --- 로그 · 피드백 ----------------------------------------------------------


def log_api_fetch(source, request_hash, status, duration_ms=None, db_path=None) -> None:
    """인증키와 요청 원문은 저장하지 않는다. 해시와 상태만 남긴다."""
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO api_fetch_logs (source, request_hash, status, duration_ms, fetched_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (source, request_hash, status, duration_ms, now()),
        )


def save_feedback(session_id, rating, reason=None, db_path=None) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO feedback (session_id, rating, reason, created_at) VALUES (?, ?, ?, ?)",
            (session_id, rating, reason, now()),
        )


def log_event(session_id, name, engine_version, screen=None, job_family_id=None, db_path=None) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO events (session_id, name, screen, job_family_id, engine_version, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, name, screen, job_family_id, engine_version, now()),
        )


# --- 재현 ------------------------------------------------------------------


def replay(session_id, db_path=None) -> dict[str, Any] | None:
    """한 세션을 통째로 되살린다. 발표 때 "이 결과가 어떻게 나왔는지" 보여줄 때 쓴다."""
    session = get_session(session_id, db_path)
    if not session:
        return None
    return {
        "session": session,
        "responses": load_responses(session_id, db_path),
        "profile": load_profile(session_id, db_path),
        "recommendations": load_recommendations(session_id, db_path),
    }
