"""Work24 / 공공데이터포털 어댑터.

설계 원칙 — 이 모듈은 실패해도 결과 화면을 깨뜨리지 않는다.

  - API 키가 없으면 아예 호출하지 않고 스냅샷만 쓴다 (mock 모드)
  - timeout 3초, 결과당 최대 1회 호출, 60초 캐시
  - 어떤 예외가 나도 스냅샷으로 내려가고, 호출 결과는 api_fetch_logs에 남긴다
  - 인증키와 요청 원문은 로그에 저장하지 않는다. 해시와 상태만 남긴다

PRD §11의 '실시간 API + 검수된 스냅샷' 이중 경로를 그대로 구현한 것이다.
"""
import hashlib
import time
import xml.etree.ElementTree as ET
from datetime import date

from p3.config import (
    CACHE_TTL_SEC,
    HTTP_TIMEOUT_SEC,
    WORK24_API_KEY,
    WORK24_JOB_INFO_URL,
    work24_enabled,
)
from p3.db import repository as repo
from p3.domain import content

SOURCE_API = "work24_job_info"

_cache = {}  # cache_key -> (expires_at, payload)


def _cache_key(params):
    raw = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _cache_get(key):
    hit = _cache.get(key)
    if not hit:
        return None
    expires_at, payload = hit
    if time.monotonic() > expires_at:
        _cache.pop(key, None)
        return None
    return payload


def _cache_put(key, payload):
    _cache[key] = (time.monotonic() + CACHE_TTL_SEC, payload)


def _normalize_param(value):
    """공백·오탈자에 따라 검색 결과가 달라지므로 요청 파라미터를 정규화한다.

    공공데이터포털 안내상 직업·채용 API는 XML 중심이며 문자열 처리에 민감하다.
    """
    return " ".join(str(value).split())


def _parse_job_info(xml_text):
    """워크넷 직업정보 XML을 최소 필드로 줄인다.

    스키마가 데이터셋마다 조금씩 다르므로 태그명을 강하게 가정하지 않고,
    흔한 이름 후보를 순서대로 찾아본다. 못 찾으면 그 항목은 버린다.
    """
    root = ET.fromstring(xml_text)
    out = []
    for item in root.iter():
        if item.tag.lower() not in ("item", "job", "jobinfo"):
            continue
        rec = {}
        for child in item:
            rec[child.tag] = (child.text or "").strip()
        name = _first(rec, ["jobNm", "jobName", "occupationNm", "title"])
        if not name:
            continue
        out.append(
            {
                "name": name,
                "external_code": _first(rec, ["jobCd", "jobCode", "occupationCd"]),
                "summary": _first(rec, ["jobDetail", "summary", "content", "jobCntnt"]),
                "source_url": _first(rec, ["jobUrl", "url", "link"]),
            }
        )
    return out


def _first(rec, keys):
    for k in keys:
        if rec.get(k):
            return rec[k]
    return None


def fetch_job_info(keyword, db_path=None):
    """직업정보를 조회한다. 실패하면 None을 돌려주고 호출자가 스냅샷으로 내려간다."""
    if not work24_enabled():
        repo.log_api_fetch(SOURCE_API, "-", "skipped_no_key", db_path=db_path)
        return None

    params = {"serviceKey": WORK24_API_KEY, "keyword": _normalize_param(keyword), "returnType": "XML"}
    # 캐시 키에 인증키를 넣지 않는다
    key = _cache_key({k: v for k, v in params.items() if k != "serviceKey"})

    cached = _cache_get(key)
    if cached is not None:
        repo.log_api_fetch(SOURCE_API, key, "cache_hit", cache_key=key, db_path=db_path)
        return cached

    started = time.monotonic()
    try:
        import requests  # 지연 import — 이 패키지가 없어도 mock 모드는 돌아가야 한다

        resp = requests.get(WORK24_JOB_INFO_URL, params=params, timeout=HTTP_TIMEOUT_SEC)
        resp.raise_for_status()
        parsed = _parse_job_info(resp.text)
        _cache_put(key, parsed)
        repo.log_api_fetch(
            SOURCE_API, key, "ok", int((time.monotonic() - started) * 1000), key, db_path=db_path
        )
        return parsed
    except Exception as exc:
        # 어떤 예외든 여기서 멈춘다. 상세 화면은 스냅샷으로 계속 그려진다.
        repo.log_api_fetch(
            SOURCE_API,
            key,
            f"error:{type(exc).__name__}",
            int((time.monotonic() - started) * 1000),
            key,
            db_path=db_path,
        )
        return None


def occupations_for(job_family_id, db_path=None):
    """직군 상세 화면용 연관 직업 목록.

    반환값에는 항상 source_label과 조회일이 붙는다. 출처 없이 화면에 올리지 않는다.
    """
    stored = repo.load_occupations(job_family_id, db_path)
    today = date.today().isoformat()
    copy = content.result_copy()["screen"]

    live = fetch_job_info(_family_keyword(job_family_id), db_path)
    live_by_name = {item["name"]: item for item in (live or [])}

    out = []
    for occ in stored:
        hit = live_by_name.get(occ["name"])
        if hit:
            out.append(
                {
                    "name": occ["name"],
                    "external_code": hit.get("external_code") or occ.get("external_code"),
                    "summary": hit.get("summary") or occ["snapshot"].get("summary"),
                    "source_url": hit.get("source_url") or occ.get("source_url"),
                    "source_label": copy["source_api"].format(date=today),
                    "from_api": True,
                }
            )
        else:
            out.append(
                {
                    "name": occ["name"],
                    "external_code": occ.get("external_code"),
                    "summary": occ["snapshot"].get("summary"),
                    "source_url": occ.get("source_url"),
                    "source_label": (occ.get("source_label") or copy["source_snapshot"]).format(
                        date=(occ.get("refreshed_at") or today)[:10]
                    )
                    if "{date}" in (occ.get("source_label") or copy["source_snapshot"])
                    else (occ.get("source_label") or copy["source_snapshot"]),
                    "from_api": False,
                }
            )

    degraded = live is None
    return {
        "occupations": out,
        "degraded": degraded,
        "notice": copy["api_failed"] if degraded and work24_enabled() else None,
    }


def _family_keyword(job_family_id):
    for fam in content.job_profiles()["job_families"]:
        if fam["job_family_id"] == job_family_id:
            return fam["name"].split("·")[0]
    return job_family_id


def clear_cache():
    _cache.clear()
