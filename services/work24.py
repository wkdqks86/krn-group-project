"""고용24/워크넷 API 어댑터. 실패하면 스냅샷으로 넘어간다."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

import requests

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "occupations.json"
# P5가 공공데이터포털 이용신청 후 실제 엔드포인트를 채운다. 비어 있으면 스냅샷만 사용.
JOB_INFO_ENDPOINT = ""
TIMEOUT_SECONDS = 5


@lru_cache(maxsize=1)
def load_snapshots() -> dict[str, Any]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def occupations_for_family(job_family_id: str) -> list[dict[str, Any]]:
    payload = load_snapshots()
    return [item for item in payload["occupations"] if item["job_family_id"] == job_family_id]


def _api_key() -> str:
    try:
        import streamlit as st

        return str(st.secrets.get("WORK24_API_KEY", "")).strip()
    except Exception:
        return ""


def fetch_job_info(keyword: str, auth_key: str | None = None) -> dict[str, Any] | None:
    """실시간 조회를 시도한다. 키가 없거나 실패하면 None."""
    key = (auth_key if auth_key is not None else _api_key()).strip()
    if not key or not keyword or not JOB_INFO_ENDPOINT:
        return None
    params = {
        "authKey": key,
        "returnType": "XML",
        "target": "jobDtl",
        "keyword": keyword,
    }
    url = f"{JOB_INFO_ENDPOINT}?{urlencode(params)}"
    try:
        response = requests.get(url, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        return {"status": "ok", "raw_tag": root.tag, "keyword": keyword}
    except (requests.RequestException, ET.ParseError):
        return None


def job_family_detail(job_family_id: str, auth_key: str | None = None) -> dict[str, Any]:
    snapshots = occupations_for_family(job_family_id)
    live_items = []
    for item in snapshots[:3]:
        live = fetch_job_info(item["name"], auth_key=auth_key)
        live_items.append({"occupation": item, "live": live})

    used_live = any(row["live"] is not None for row in live_items)
    return {
        "job_family_id": job_family_id,
        "occupations": snapshots,
        "live_attempted": bool((auth_key if auth_key is not None else _api_key()).strip()),
        "used_live_api": used_live,
        "source_label": (
            "한국고용정보원 Work24 (실시간)"
            if used_live
            else f"팀 검수 스냅샷(원본 갱신일 {load_snapshots().get('snapshot_date', '-')})"
        ),
    }
