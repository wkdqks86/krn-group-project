"""사용자 12축 벡터를 성향 프로파일(레이더 데이터·유형 요약·강점/성장포인트)로 바꾼다.

점수를 다시 계산하지 않는다 — domain.scoring이 만든 user_vector를 그대로 읽어
순위만 매기고, 문구는 data/personality_content.json(P2 소유)에서 가져온다.
파일이 없으면 화면이 죽지 않도록 안전한 기본값으로 동작한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from domain.scoring import AXES, AXIS_LABELS

RIASEC_AXES = AXES[:6]

_CONTENT_PATH = Path(__file__).resolve().parents[1] / "data" / "personality_content.json"

_FALLBACK = {
    "riasec_root": {"R": "현실", "I": "탐구", "A": "예술", "S": "사회", "E": "진취", "C": "관습"},
    "riasec_phrase": {
        "R": "직접 만들고 확인하는",
        "I": "원리를 파고드는",
        "A": "새롭게 표현하는",
        "S": "사람을 돕고 소통하는",
        "E": "목표를 이끌고 설득하는",
        "C": "체계를 정리하고 운영하는",
    },
    "type_description_template": "'{root1}-{root2}형' 성향이 함께 도드라져요. {phrase1} 힘과 {phrase2} 힘을 동시에 갖고 있는 조합이에요.",
    "strengths_heading": "강점으로 보이는 부분",
    "growth_points_heading": "낯설게 느껴질 수 있는 부분",
    "growth_points_note": "이 부분이 약하다는 뜻이 아니라, 상대적으로 덜 익숙할 수 있다는 뜻이에요.",
    "axis_strength_text": {},
    "axis_growth_text": {},
}


def _load_content() -> dict[str, Any]:
    try:
        data = json.loads(_CONTENT_PATH.read_text(encoding="utf-8"))
        merged = dict(_FALLBACK)
        merged.update(data)
        return merged
    except (OSError, ValueError):
        return dict(_FALLBACK)


_CONTENT = _load_content()


def top_axes(user_vector: dict[str, float], n: int = 3, axes: list[str] | None = None) -> list[str]:
    pool = axes or AXES
    ranked = sorted(pool, key=lambda a: user_vector.get(a, 0), reverse=True)
    return ranked[:n]


def bottom_axes(user_vector: dict[str, float], n: int = 2, axes: list[str] | None = None) -> list[str]:
    pool = axes or AXES
    ranked = sorted(pool, key=lambda a: user_vector.get(a, 0))
    return ranked[:n]


def riasec_type(user_vector: dict[str, float]) -> dict[str, str]:
    a1, a2 = top_axes(user_vector, n=2, axes=RIASEC_AXES)
    roots = _CONTENT["riasec_root"]
    phrases = _CONTENT["riasec_phrase"]
    name = f"{roots[a1]}-{roots[a2]}형"
    description = _CONTENT["type_description_template"].format(
        root1=roots[a1], root2=roots[a2], phrase1=phrases[a1], phrase2=phrases[a2]
    )
    return {"code": a1 + a2, "name": name, "description": description}


def strength_lines(user_vector: dict[str, float], n: int = 3) -> list[str]:
    texts = _CONTENT["axis_strength_text"]
    return [texts[a] for a in top_axes(user_vector, n=n) if a in texts]


def growth_lines(user_vector: dict[str, float], n: int = 2) -> list[str]:
    texts = _CONTENT["axis_growth_text"]
    return [texts[a] for a in bottom_axes(user_vector, n=n) if a in texts]


def radar_data(user_vector: dict[str, float]) -> dict[str, list]:
    return {
        "axes": [AXIS_LABELS[a] for a in AXES],
        "values": [round(user_vector.get(a, 0), 1) for a in AXES],
    }


def personality_profile(user_vector: dict[str, float]) -> dict[str, Any]:
    return {
        "type": riasec_type(user_vector),
        "strengths": strength_lines(user_vector),
        "growth_points": growth_lines(user_vector),
        "radar": radar_data(user_vector),
        "strengths_heading": _CONTENT["strengths_heading"],
        "growth_points_heading": _CONTENT["growth_points_heading"],
        "growth_points_note": _CONTENT["growth_points_note"],
    }
