"""고용24/워크넷 API 어댑터. 실패하면 스냅샷으로 넘어간다.

키가 없으면 호출하지 않고, timeout·캐시를 쓰며,
어떤 예외가 나도 화면은 스냅샷으로 계속 그린다. 인증키는 로그에 남기지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import time
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "occupations.json"
JOB_INFO_ENDPOINT = ""
TIMEOUT_SECONDS = 3.0
CACHE_TTL_SEC = 60

_cache: dict[str, tuple[float, Any]] = {}


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


def _cache_key(params: dict[str, str]) -> str:
    raw = "&".join(f"{key}={value}" for key, value in sorted(params.items()))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def fetch_job_info(keyword: str, auth_key: str | None = None) -> dict[str, Any] | None:
    """실시간 조회를 시도한다. 키가 없거나 실패하면 None."""
    key = (auth_key if auth_key is not None else _api_key()).strip()
    if not key or not keyword or not JOB_INFO_ENDPOINT:
        return None
    params = {
        "authKey": key,
        "returnType": "XML",
        "target": "jobDtl",
        "keyword": " ".join(str(keyword).split()),
    }
    cache_key = _cache_key({name: value for name, value in params.items() if name != "authKey"})
    hit = _cache.get(cache_key)
    if hit and time.monotonic() <= hit[0]:
        return hit[1]
    if hit:
        _cache.pop(cache_key, None)

    try:
        import requests

        url = f"{JOB_INFO_ENDPOINT}?{urlencode(params)}"
        response = requests.get(url, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        payload = {"status": "ok", "raw_tag": root.tag, "keyword": keyword}
        _cache[cache_key] = (time.monotonic() + CACHE_TTL_SEC, payload)
        return payload
    except Exception:
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
