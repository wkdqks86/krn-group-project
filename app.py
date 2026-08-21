import json
import random
from pathlib import Path

import plotly.graph_objects as pgo
import streamlit as st

from domain.branching import (
    CLUSTER_ORDER,
    build_user_profile,
    common_sjt_questions,
    followup_questions_for_clusters,
    likert_questions,
    visible_question_queue,
)
from domain.scoring import ENGINE_VERSION, rank_job_families
from services.explainer import explain_recommendation
from services.personality import personality_profile
from services.work24 import job_family_detail

ROOT = Path(__file__).resolve().parent
DISCLAIMER = (
    "이 결과는 취업 성공 가능성이나 능력을 판정하지 않습니다. "
    "현재 입력한 프로파일과 각 직군의 초기 요구 프로파일 사이의 상대적 적합도를 보여주는 탐색 가이드입니다."
)
STEPS = ["landing", "optional", "diagnose", "context", "result", "detail", "feedback"]
MODULE_ORDER = ["riasec", "competency", "sjt_common", "sjt_followup"]
RESULT_RANK_STYLES = {
    1: {"emoji": "🥇", "accent": "#d4a017", "bg": "linear-gradient(135deg, #fff9e6 0%, #ffffff 100%)"},
    2: {"emoji": "🥈", "accent": "#7a8a99", "bg": "linear-gradient(135deg, #f4f7fa 0%, #ffffff 100%)"},
    3: {"emoji": "🥉", "accent": "#b87333", "bg": "linear-gradient(135deg, #fff4eb 0%, #ffffff 100%)"},
}
RESULT_SECTION_ICONS = {
    "reasons": ":material/lightbulb:",
    "cautions": ":material/flag:",
    "actions": ":material/rocket_launch:",
    "growth": ":material/trending_up:",
    "glossary": ":material/menu_book:",
}


def load_json(name: str):
    return json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))


def init_state():
    st.session_state.setdefault("step", "landing")
    st.session_state.setdefault("consent", False)
    st.session_state.setdefault("responses", {})
    st.session_state.setdefault("optional_traits", {})
    st.session_state.setdefault("context", {})
    st.session_state.setdefault("user_vector", None)
    st.session_state.setdefault("recommendations", [])
    st.session_state.setdefault("selected_job_id", None)
    st.session_state.setdefault("feedback", {})


def build_module_shuffles(questions_payload: dict, seed: int) -> dict[str, list[str]]:
    """모듈(카테고리) 순서는 유지하고, 같은 응답 단계(리커트/SJT)끼리만 섞는다."""
    rng = random.Random(seed)
    shuffles: dict[str, list[str]] = {}
    for module in MODULE_ORDER:
        question_ids = [
            item["question_id"]
            for item in questions_payload["questions"]
            if item.get("module") == module
        ]
        rng.shuffle(question_ids)
        shuffles[module] = question_ids
    return shuffles


def ensure_question_shuffle(questions_payload: dict):
    if "question_shuffle" not in st.session_state:
        st.session_state.question_shuffle_seed = random.randint(0, 2**31 - 1)
        st.session_state.question_shuffle = build_module_shuffles(
            questions_payload, st.session_state.question_shuffle_seed
        )


def apply_question_shuffle(base_queue: list[dict], shuffle_map: dict[str, list[str]]) -> list[dict]:
    by_id = {item["question_id"]: item for item in base_queue}
    ordered: list[dict] = []
    for module in MODULE_ORDER:
        for question_id in shuffle_map.get(module, []):
            if question_id in by_id:
                ordered.append(by_id[question_id])
    return ordered


def get_diagnosis_queue(questions_payload: dict, responses: dict) -> list[dict]:
    ensure_question_shuffle(questions_payload)
    base_queue = visible_question_queue(questions_payload, responses)
    return apply_question_shuffle(base_queue, st.session_state.question_shuffle)


def reset_session():
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    init_state()


def go(step: str):
    st.session_state.step = step


def diagnosis_question_total(questions_payload: dict) -> int:
    """후속 SJT가 나중에 붙더라도, 사용자에게는 처음부터 전체 문항 수를 고정해 보여준다."""
    base = len(likert_questions(questions_payload)) + len(common_sjt_questions(questions_payload))
    followup = len(followup_questions_for_clusters(questions_payload, CLUSTER_ORDER[:2]))
    return base + followup


def render_choice_grid(
    options: list[tuple[object, str]],
    state_key: str,
    columns: int = 3,
    *,
    question_id: str | None = None,
    auto_submit: bool = False,
):
    selected = st.session_state.get(state_key)
    cols = st.columns(columns)
    for idx, (value, label) in enumerate(options):
        with cols[idx % columns]:
            if st.button(
                label,
                key=f"{state_key}_option_{idx}",
                use_container_width=True,
                type="primary" if selected == value else "secondary",
            ):
                st.session_state[state_key] = value
                if auto_submit and question_id is not None:
                    st.session_state.responses[question_id] = value
                st.rerun()
    return selected


def escape_html(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_result_section(kind: str, title: str, lines: list[str], icon: str):
    if not lines:
        return
    items_html = "".join(f"<li>{escape_html(line)}</li>" for line in lines)
    safe_title = escape_html(title)
    st.markdown(
        f"""
        <div class="result-section-box {kind}">
          <p class="result-section-title">{icon} {safe_title}</p>
          <ul class="result-section-list">{items_html}</ul>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_personality_type_box(description: str, combo_note: str):
    st.markdown(
        f"""
        <div class="personality-type-box">
          <p class="personality-type-desc">{escape_html(description)}</p>
          <p class="personality-type-note">{escape_html(combo_note)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_personality_insight_box(
    kind: str,
    title: str,
    lines: list[str],
    icon: str,
    note: str = "",
):
    items_html = "".join(f"<li>{escape_html(line)}</li>" for line in lines)
    note_html = f'<p class="personality-insight-note">{escape_html(note)}</p>' if note else ""
    st.markdown(
        f"""
        <div class="personality-insight-box {kind}">
          <p class="personality-insight-title">{icon} {escape_html(title)}</p>
          {note_html}
          <ul class="personality-insight-list">{items_html}</ul>
        </div>
        """,
        unsafe_allow_html=True,
    )


st.set_page_config(page_title="잠재력 발견", page_icon=":material/explore:", layout="centered")
init_state()
questions_payload = load_json("questions.json")
profiles_payload = load_json("job_profiles.json")
likert_labels = questions_payload["likert_labels"]
copy = load_json("copy.json")
SCREEN = copy["screens"]
current_step = st.session_state.step
compact_steps = {"diagnose", "detail"}

st.markdown(
    """
    <style>
    .landing-hero {
        background: linear-gradient(180deg, #f3f9ff 0%, #ffffff 100%);
        border: 1px solid #d7e9ff;
        border-radius: 16px;
        padding: 24px 22px;
        margin-bottom: 14px;
        text-align: center;
        box-shadow: 0 8px 24px rgba(15, 36, 64, 0.05);
    }
    .landing-chip {
        display: inline-block;
        font-size: 12px;
        font-weight: 600;
        color: #0b5cab;
        background: #e9f3ff;
        border: 1px solid #cfe5ff;
        border-radius: 999px;
        padding: 4px 10px;
        margin-bottom: 10px;
    }
    .page-title {
        font-size: 4rem !important;
        font-weight: 800;
        color: #0f2440;
        text-align: center;
        margin: 8px 0 4px 0;
        line-height: 1.2;
    }
    .page-subtitle {
        font-size: 16px;
        font-weight: 500;
        color: #5a6f89;
        text-align: center;
        margin: 0 0 14px 0;
    }
    .landing-title {
        font-size: 30px;
        font-weight: 800;
        color: #0f2440;
        line-height: 1.25;
        margin-bottom: 8px;
    }
    .landing-subtitle {
        font-size: 15px;
        color: #38506e;
        line-height: 1.6;
        margin-bottom: 0;
    }
    .landing-section-title {
        font-size: 16px;
        font-weight: 700;
        color: #17365d;
        margin: 12px 0 6px 0;
    }
    .landing-section-chip {
        display: inline-block;
        font-size: 14px;
        font-weight: 700;
        color: #0b5cab;
        background: #e9f3ff;
        border: 1px solid #cfe5ff;
        border-radius: 999px;
        padding: 5px 12px;
        margin: 12px 0 8px 0;
        line-height: 1.2;
    }
    .landing-note {
        font-size: 13px;
        color: #5a6f89;
        margin: 0 0 12px 0;
        text-align: center;
        line-height: 1.5;
    }
    .landing-kpi-box {
        background: #ffffff;
        border: 1px solid #d7e9ff;
        border-radius: 14px;
        padding: 16px 14px;
        margin-bottom: 10px;
        text-align: center;
        box-shadow: 0 4px 14px rgba(15, 36, 64, 0.04);
    }
    .landing-kpi-label {
        font-size: 16px;
        font-weight: 600;
        color: #17365d;
        margin: 0 0 6px 0;
        line-height: 1.3;
    }
    .landing-kpi-value {
        font-size: 30px;
        font-weight: 800;
        color: #0f2440;
        margin: 0 0 8px 0;
        line-height: 1.15;
    }
    .landing-kpi-desc {
        font-size: 14px;
        color: #4a6280;
        margin: 0;
        line-height: 1.5;
    }
    .landing-steps-line {
        font-size: 16px;
        font-weight: 600;
        color: #1b7f4b;
        line-height: 1.6;
        margin: 0;
        text-align: center;
    }
    .landing-steps-box {
        background: #f7fbff;
        border: 1px solid #d7e9ff;
        border-radius: 12px;
        padding: 10px 12px;
        margin-bottom: 6px;
    }
    .landing-disclaimer-box {
        background: linear-gradient(180deg, #f7fbff 0%, #ffffff 100%);
        border: 1px solid #d7e9ff;
        border-radius: 12px;
        padding: 14px 16px;
        margin-bottom: 10px;
    }
    .landing-disclaimer-text {
        margin: 0;
        color: #2b3f57;
        font-size: 0.95rem;
        line-height: 1.65;
        font-weight: 500;
    }
    .landing-consent-heading {
        margin: 0 0 12px 0;
        font-size: 0.92rem;
        font-weight: 700;
        color: #5a6f89;
        text-align: center;
        line-height: 1.5;
    }
    div[data-testid="stCheckbox"] > label {
        background: #ffffff;
        border: 1px solid #d7e9ff;
        border-radius: 12px;
        padding: 14px 20px;
        width: max-content !important;
        max-width: none !important;
        box-shadow: 0 2px 8px rgba(15, 36, 64, 0.03);
        transition: border-color 0.15s ease, background 0.15s ease;
        display: inline-flex !important;
        align-items: center;
        gap: 10px;
        box-sizing: border-box;
        white-space: nowrap !important;
    }
    div[data-testid="stCheckbox"] {
        width: max-content !important;
        max-width: none !important;
        padding: 0;
        margin: 0 0 12px 0;
    }
    div[data-testid="stCheckbox"] > label:hover {
        border-color: #9ec8f5;
        background: #f7fbff;
    }
    div[data-testid="stCheckbox"] p,
    div[data-testid="stCheckbox"] [data-testid="stMarkdownContainer"],
    div[data-testid="stCheckbox"] [data-testid="stMarkdownContainer"] p {
        font-size: 0.98rem !important;
        font-weight: 600 !important;
        color: #17365d !important;
        line-height: 1.55 !important;
        margin: 0 !important;
        white-space: nowrap !important;
    }
    .diagnose-module-chip {
        display: inline-block;
        font-size: 14px;
        font-weight: 700;
        color: #0b5cab;
        background: #e9f3ff;
        border: 1px solid #cfe5ff;
        border-radius: 999px;
        padding: 6px 14px;
        margin: 4px 0 10px 0;
        line-height: 1.2;
    }
    .page-section-chip {
        display: inline-block;
        font-size: 20px;
        font-weight: 800;
        color: #0b5cab;
        background: #e9f3ff;
        border: 1px solid #cfe5ff;
        border-radius: 999px;
        padding: 8px 16px;
        margin: 0 0 12px 0;
        line-height: 1.2;
    }
    .diagnose-shell {
        min-height: calc(100vh - 1.5rem);
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        gap: 0.35rem;
        padding-bottom: 0.25rem;
    }
    .diagnose-top {
        flex: 0 0 auto;
    }
    .diagnose-progress-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 4px;
    }
    .diagnose-progress-meta {
        font-size: 13px;
        font-weight: 700;
        color: #17365d;
        white-space: nowrap;
    }
    .diagnose-prompt-box {
        background: #ffffff;
        border: 1px solid #d7e9ff;
        border-radius: 14px;
        padding: 14px 16px;
        margin: 6px 0 8px 0;
        min-height: 72px;
        display: flex;
        align-items: center;
        justify-content: center;
        text-align: center;
        font-size: 1.05rem;
        font-weight: 700;
        color: #0f2440;
        line-height: 1.45;
    }
    .diagnose-hint {
        font-size: 12px;
        color: #5a6f89;
        margin: 0;
        text-align: center;
    }
    .diagnose-choices-wrap {
        flex: 1 1 auto;
        display: flex;
        flex-direction: column;
        justify-content: center;
        gap: 0.35rem;
        padding: 0.15rem 0;
    }
    .diagnose-choices-wrap div[data-testid="column"] button {
        min-height: 2.75rem;
        padding: 0.35rem 0.4rem;
        font-size: 0.82rem;
        line-height: 1.25;
        white-space: normal;
    }
    .diagnose-nav {
        flex: 0 0 auto;
        margin-top: 0.15rem;
    }
    .diagnose-compact-title {
        font-size: 1.35rem;
        font-weight: 800;
        color: #0f2440;
        margin: 0 0 2px 0;
        text-align: center;
    }
    .result-hero {
        background: linear-gradient(135deg, #eef6ff 0%, #ffffff 55%);
        border: 1px solid #cfe5ff;
        border-radius: 18px;
        padding: 18px 20px;
        margin-bottom: 14px;
        text-align: center;
    }
    .result-hero-title {
        font-size: 1.75rem;
        font-weight: 800;
        color: #0f2440;
        margin: 0 0 6px 0;
    }
    .result-hero-sub {
        font-size: 0.95rem;
        color: #4a6280;
        margin: 0;
    }
    .result-card {
        border-radius: 16px;
        padding: 16px 18px;
        margin-bottom: 14px;
        border: 1px solid #d7e9ff;
        box-shadow: 0 6px 18px rgba(15, 36, 64, 0.05);
    }
    .result-card-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        margin-bottom: 10px;
    }
    .result-rank-badge {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        font-size: 1.35rem;
        font-weight: 800;
        color: #0f2440;
    }
    .result-score-pill {
        display: inline-block;
        font-size: 0.95rem;
        font-weight: 800;
        padding: 6px 12px;
        border-radius: 999px;
        background: #e9f3ff;
        color: #0b5cab;
        border: 1px solid #cfe5ff;
    }
    .result-band-chip {
        display: inline-block;
        font-size: 0.82rem;
        font-weight: 700;
        padding: 4px 10px;
        border-radius: 999px;
        margin-bottom: 10px;
    }
    .result-section-box {
        background: #ffffff;
        border: 1px solid #d7e9ff;
        border-radius: 14px;
        padding: 14px 16px;
        margin: 0 0 12px 0;
        box-shadow: 0 3px 12px rgba(15, 36, 64, 0.04);
    }
    .result-section-box.reasons {
        border-left: 0;
        background: linear-gradient(180deg, #f7fbff 0%, #ffffff 100%);
    }
    .result-section-box.cautions {
        border-left: 0;
        background: linear-gradient(180deg, #fffaf2 0%, #ffffff 100%);
    }
    .result-section-box.actions {
        border-left: 0;
        background: linear-gradient(180deg, #f4fbf7 0%, #ffffff 100%);
    }
    .result-section-box.growth {
        border-left: 0;
        background: linear-gradient(180deg, #f8f6ff 0%, #ffffff 100%);
    }
    .result-section-box.glossary {
        border-left: 0;
        background: linear-gradient(180deg, #f7f9fb 0%, #ffffff 100%);
    }
    .result-section-title {
        font-size: 1.02rem;
        font-weight: 800;
        color: #17365d;
        margin: 0 0 8px 0;
        line-height: 1.35;
    }
    .result-section-list {
        margin: 0;
        padding-left: 1.15rem;
        color: #2b3f57;
        line-height: 1.55;
        font-size: 0.95rem;
    }
    .result-section-list li {
        margin-bottom: 6px;
    }
    .personality-panel {
        background: linear-gradient(180deg, #f8fbff 0%, #ffffff 100%);
        border: 1px solid #d7e9ff;
        border-radius: 18px;
        padding: 18px 18px 10px 18px;
        margin-bottom: 18px;
        box-shadow: 0 8px 24px rgba(15, 36, 64, 0.06);
    }
    .personality-panel-title {
        font-size: 1.35rem;
        font-weight: 800;
        color: #0f2440;
        margin: 0 0 12px 0;
        line-height: 1.35;
    }
    .personality-type-box {
        background: #ffffff;
        border: 1px solid #cfe5ff;
        border-radius: 14px;
        padding: 16px 18px;
        margin-bottom: 14px;
        box-shadow: 0 3px 12px rgba(11, 92, 171, 0.06);
    }
    .personality-type-desc {
        margin: 0 0 10px 0;
        color: #2b3f57;
        font-size: 1rem;
        line-height: 1.65;
        font-weight: 500;
    }
    .personality-type-note {
        margin: 0;
        color: #5a6f89;
        font-size: 0.92rem;
        line-height: 1.55;
        padding-top: 10px;
        border-top: 1px dashed #d7e9ff;
    }
    .personality-radar-box {
        background: #ffffff;
        border: 1px solid #e8f1fb;
        border-radius: 14px;
        padding: 8px 8px 0 8px;
        margin-bottom: 14px;
    }
    .personality-insights-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 12px;
        margin-bottom: 4px;
    }
    @media (max-width: 768px) {
        .personality-insights-grid {
            grid-template-columns: 1fr;
        }
    }
    .personality-insight-box {
        background: #ffffff;
        border: 1px solid #d7e9ff;
        border-radius: 14px;
        padding: 14px 16px;
        height: 100%;
        box-shadow: 0 3px 12px rgba(15, 36, 64, 0.04);
    }
    .personality-insight-box.strengths {
        background: linear-gradient(180deg, #f4fbf7 0%, #ffffff 100%);
    }
    .personality-insight-box.unfamiliar {
        background: linear-gradient(180deg, #f8f6ff 0%, #ffffff 100%);
    }
    .personality-insight-title {
        font-size: 1rem;
        font-weight: 800;
        color: #17365d;
        margin: 0 0 8px 0;
        line-height: 1.35;
    }
    .personality-insight-note {
        margin: 0 0 8px 0;
        color: #5a6f89;
        font-size: 0.88rem;
        line-height: 1.5;
    }
    .personality-insight-list {
        margin: 0;
        padding-left: 1.1rem;
        color: #2b3f57;
        line-height: 1.6;
        font-size: 0.94rem;
    }
    .personality-insight-list li {
        margin-bottom: 8px;
    }
    .personality-card-title {
        font-size: 1.25rem;
        font-weight: 800;
        color: #0f2440;
    }
    .optional-note-box {
        background: #ffffff;
        border: 1px solid #d7e9ff;
        border-radius: 14px;
        padding: 14px 16px;
        margin: 0 0 12px 0;
        box-shadow: 0 3px 12px rgba(15, 36, 64, 0.04);
    }
    .optional-note-text {
        margin: 0;
        color: #2b3f57;
        font-size: 1rem;
        font-weight: 500;
        line-height: 1.6;
    }
    .optional-field-box {
        background: #ffffff;
        border: 1px solid #d7e9ff;
        border-radius: 14px;
        padding: 14px 16px 10px 16px;
        margin: 0 0 12px 0;
        box-shadow: 0 3px 12px rgba(15, 36, 64, 0.04);
    }
    .optional-field-label {
        margin: 0 0 8px 0;
        color: #2b3f57;
        font-size: 1rem;
        font-weight: 500;
        line-height: 1.6;
    }
    
    /* Detail 화면(연관 직업) 카드 스타일 */
    .detail-hero {
        background: linear-gradient(135deg, #eef6ff 0%, #ffffff 55%);
        border: 1px solid #cfe5ff;
        border-radius: 18px;
        padding: 22px 22px;
        margin-bottom: 16px;
        text-align: center;
    }
    .detail-hero-title {
        font-size: 2.55rem !important;
        font-weight: 900;
        color: #0f2440;
        margin: 0 0 10px 0;
        line-height: 1.2;
        letter-spacing: -0.03em;
    }
    .detail-hero-sub {
        font-size: 1rem;
        color: #4a6280;
        margin: 0;
        line-height: 1.65;
        font-weight: 500;
    }
    .detail-section-title-box {
        background: #ffffff;
        border: 1px solid #cfe5ff;
        border-radius: 14px;
        padding: 14px 16px;
        margin: 0 0 14px 0;
        box-shadow: 0 4px 14px rgba(15, 36, 64, 0.05);
        text-align: center;
    }
    .detail-section-title {
        margin: 0;
        font-size: 1.7rem !important;
        font-weight: 900;
        color: #17365d;
        line-height: 1.3;
    }
    .detail-occupation-card {
        border-radius: 16px;
        border: 1px solid #d7e9ff;
        background: #ffffff;
        box-shadow: 0 6px 18px rgba(15, 36, 64, 0.04);
        padding: 16px 16px;
        margin-bottom: 12px;
    }
    .detail-occupation-name {
        font-size: 1.18rem !important;
        font-weight: 800;
        color: #0f2440;
        margin: 0 0 8px 0;
        line-height: 1.35;
    }
    .detail-occupation-summary {
        margin: 0 0 8px 0;
        color: #2b3f57;
        line-height: 1.6;
        font-size: 0.98rem;
        font-weight: 500;
    }
    .detail-occupation-hint {
        margin: 0 0 8px 0;
        color: #5a6f89;
        font-size: 0.92rem;
        line-height: 1.55;
    }

    /* "연관 직업 보기" 버튼만 진하게 보이도록 */
    button[aria-label="연관 직업 보기"] {
        background: linear-gradient(180deg, #0b5cab 0%, #084c8a 100%) !important;
        color: #ffffff !important;
        border: 0 !important;
        border-radius: 12px !important;
        font-weight: 900 !important;
        padding: 0.65rem 1rem !important;
        box-shadow: 0 10px 22px rgba(11, 92, 171, 0.18) !important;
    }

    section[data-testid="stSidebar"] {
        min-width: 220px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

if current_step not in compact_steps:
    st.markdown('<p class="page-title">잠재력 발견</p>', unsafe_allow_html=True)
    st.markdown(
        f'<p class="page-subtitle">20~30대 취업준비생을 위한 직군 탐색 MVP · engine {ENGINE_VERSION}</p>',
        unsafe_allow_html=True,
    )

with st.sidebar:
    st.subheader("진행")
    st.write(f"현재 단계: {st.session_state.step}")
    if st.button("처음부터 다시", icon=":material/refresh:"):
        reset_session()
        st.rerun()

if st.session_state.step == "landing":
    st.markdown(
        """
        <div class="landing-hero">
          <div class="landing-chip">취업 탐색 가이드</div>
          <div class="landing-title">지금의 나에게 맞는 직군을<br/>명확하게 좁혀보세요</div>
          <p class="landing-subtitle">
            약 10분 동안 흥미·업무 방식·상황 판단에 답하면,<br/>
            8개 대분류 직군 중 상대적으로 가까운 TOP 5를 보여드립니다.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="landing-section-chip">한눈에 보는 진단 정보</div>', unsafe_allow_html=True)
    info_col1, info_col2, info_col3 = st.columns(3)
    info_col1.markdown(
        (
            '<div class="landing-kpi-box">'
            '<p class="landing-kpi-label">소요 시간</p>'
            '<p class="landing-kpi-value">약 10분</p>'
            '<p class="landing-kpi-desc">복잡한 검사가 아닌 짧은 탐색형 진단입니다.</p>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )
    info_col2.markdown(
        (
            '<div class="landing-kpi-box">'
            '<p class="landing-kpi-label">분석 축</p>'
            '<p class="landing-kpi-value">12개</p>'
            '<p class="landing-kpi-desc">흥미 6축 + 핵심역량 6축으로 비교합니다.</p>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )
    info_col3.markdown(
        (
            '<div class="landing-kpi-box">'
            '<p class="landing-kpi-label">결과</p>'
            '<p class="landing-kpi-value">TOP 5 직군</p>'
            '<p class="landing-kpi-desc">탐색 우선순위와 확인 포인트를 제공합니다.</p>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    st.markdown('<div class="landing-section-chip">진행 단계</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="landing-steps-box"><p class="landing-steps-line">안내 확인 → 자기이해 입력(선택) → 핵심 진단 → 현실 조건 → 결과 확인</p></div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="landing-section-chip">시작 전 확인</div>', unsafe_allow_html=True)

    with st.container(border=True):
        st.markdown(
        f"""
        <div class="landing-disclaimer-box">
        <p class="landing-disclaimer-text">{escape_html(DISCLAIMER)}</p>
        </div>
        <p class="landing-note">결과는 합격 가능성·능력 판정이 아닌, 탐색 우선순위 안내입니다.</p>
        <p class="landing-consent-heading">아래 내용을 확인한 뒤 체크하고 진단을 시작해 주세요.</p>
        """,
        unsafe_allow_html=True,
    )

    with st.container(
        horizontal=True,
        horizontal_alignment="center",
        gap=None,
    ):
        st.checkbox(
            "안내를 확인했고, 결과가 합격·능력 판정이 아님을 이해합니다.",
            key="consent",
            width="content",
        )

    st.button(
        "진단 시작",
        type="primary",
        icon=":material/play_arrow:",
        disabled=not st.session_state.consent,
        on_click=go,
        args=("optional",),
        use_container_width=True,
    )


elif st.session_state.step == "optional":
    st.markdown(
        '<div class="page-section-chip">기존 자기 이해 정보</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="optional-note-box">
          <p class="optional-note-text">
            선택 입력입니다. 모르면 건너뛰어도 되고, 직군 점수에는 반영되지 않습니다.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    saved_traits = st.session_state.get("optional_traits") or {}

    mbti_options = [
        "모름 / 건너뛰기",
        "ISTJ",
        "ISFJ",
        "INFJ",
        "INTJ",
        "ISTP",
        "ISFP",
        "INFP",
        "INTP",
        "ESTP",
        "ESFP",
        "ENFP",
        "ENTP",
        "ESTJ",
        "ESFJ",
        "ENFJ",
        "ENTJ",
    ]

    enneagram_options = [
        "모름 / 건너뛰기",
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
    ]

    mbti_default = saved_traits.get("mbti")
    enneagram_default = saved_traits.get("enneagram")

    with st.container(border=True):
        st.markdown('<p class="optional-field-label">MBTI</p>', unsafe_allow_html=True)
        mbti = st.selectbox(
            "MBTI",
            mbti_options,
            index=mbti_options.index(mbti_default) if mbti_default in mbti_options else 0,
            label_visibility="collapsed",
            key="optional_mbti_select",
        )

    with st.container(border=True):
        st.markdown('<p class="optional-field-label">애니어그램</p>', unsafe_allow_html=True)
        enneagram = st.selectbox(
            "애니어그램",
            enneagram_options,
            index=enneagram_options.index(str(enneagram_default)) if enneagram_default in enneagram_options else 0,
            label_visibility="collapsed",
            key="optional_enneagram_select",
        )

    with st.container(horizontal=True):
        if st.button("이전", icon=":material/arrow_back:"):
            go("landing")
            st.rerun()
        if st.button("다음", type="primary", icon=":material/arrow_forward:"):
            st.session_state.optional_traits = {
                "mbti": None if mbti.startswith("모름") else mbti,
                "enneagram": None if enneagram.startswith("모름") else enneagram,
            }
            go("diagnose")
            st.rerun()

elif st.session_state.step == "diagnose":
    queue = get_diagnosis_queue(questions_payload, st.session_state.responses)
    answered_ids = [item["question_id"] for item in queue if item["question_id"] in st.session_state.responses]
    current = next((item for item in queue if item["question_id"] not in st.session_state.responses), None)
    total_questions = diagnosis_question_total(questions_payload)
    answered_count = len(answered_ids)
    module_labels = {
        "riasec": "일반흥미",
        "competency": "업무역량",
        "sjt_common": "공통 상황판단",
        "sjt_followup": "후속 상황판단",
    }


    if current is None:
        go("context")
        st.rerun()

    step_no = answered_count + 1
    module_label = module_labels.get(current.get("module", ""), "진단 문항")
    answer_key = f"choice_{current['question_id']}"
    progress_ratio = min(1.0, answered_count / max(total_questions, 1))

    st.markdown(
        """
        <style>
        .main .block-container { padding-top: 0.35rem; padding-bottom: 0.35rem; max-width: 880px; }
        header[data-testid="stHeader"] { visibility: hidden; height: 0; }
        div[data-testid="stProgress"] { margin-bottom: 0.15rem; }
        .diagnose-progress-box {
            background: #ffffff;
            border: 1px solid #d7e9ff;
            border-radius: 14px;
            padding: 14px 16px;
            margin: 0 0 12px 0;
            box-shadow: 0 3px 12px rgba(15, 36, 64, 0.04);
        }
        .diagnose-compact-title {
            font-size: 1rem;
            font-weight: 700;
            color: #17365d;
            margin: 0 0 8px 0;
            text-align: center;
            line-height: 1.35;
        }
        .diagnose-progress-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            margin-bottom: 8px;
        }
        .diagnose-progress-meta {
            font-size: 1rem;
            font-weight: 700;
            color: #17365d;
            white-space: nowrap;
            line-height: 1.35;
        }
        .diagnose-prompt-box {
            background: #ffffff;
            border: 1px solid #d7e9ff;
            border-radius: 14px;
            padding: 14px 16px;
            margin: 6px 0 8px 0;
            min-height: 72px;
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
            font-size: 1.05rem;
            font-weight: 700;
            color: #0f2440;
            line-height: 1.45;
        }
        .diagnose-hint {
            font-size: 12px;
            color: #5a6f89;
            margin: 0 0 6px 0;
            text-align: center;
        }
        div[data-testid="column"] button {
            min-height: 2.75rem;
            padding: 0.35rem 0.4rem;
            font-size: 0.82rem;
            line-height: 1.25;
            white-space: pre-line;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        st.markdown(
            f"""
            <p class="diagnose-compact-title">응답 진행률</p>
            <div class="diagnose-progress-row">
              <span class="diagnose-progress-meta">STEP {step_no:02d}/{total_questions:02d} · {module_label}</span>
              <span class="diagnose-progress-meta">{answered_count}/{total_questions}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.progress(progress_ratio)

    st.markdown(
        f'<div class="diagnose-prompt-box">{current["prompt"]}</div>',
        unsafe_allow_html=True,
    )

    if current["type"] == "likert":
        likert_display = {
            5: "매우\n그렇다",
            4: "그렇다",
            3: "보통",
            2: "아니다",
            1: "전혀\n아니다",
        }
        likert_options = [
            (5, likert_display[5]),
            (4, likert_display[4]),
            (3, likert_display[3]),
            (2, likert_display[2]),
            (1, likert_display[1]),
        ]
        choice = render_choice_grid(
            likert_options,
            state_key=answer_key,
            columns=5,
            question_id=current["question_id"],
            auto_submit=False,
        )
    else:
        sjt_options = [(option["option_id"], option["label"]) for option in current["options"]]
        choice = render_choice_grid(
            sjt_options,
            state_key=answer_key,
            columns=2,
            question_id=current["question_id"],
            auto_submit=False,
        )

    nav_prev, nav_next = st.columns(2)
    with nav_prev:
        if st.button("이전", icon=":material/arrow_back:", use_container_width=True):
            if answered_ids:
                last_id = answered_ids[-1]
                del st.session_state.responses[last_id]
                st.session_state.pop(f"choice_{last_id}", None)
            else:
                go("optional")
            st.rerun()
    with nav_next:
        if st.button(
            "다음",
            icon=":material/arrow_forward:",
            use_container_width=True,
            disabled=choice is None,
        ):
            st.session_state.responses[current["question_id"]] = choice
            st.rerun()

elif st.session_state.step == "context":
    st.markdown('<div class="page-section-chip">추가 정보 입력</div>', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="optional-note-box">
          <p class="optional-note-text">추천 점수에는 더하지 않습니다. 결과의 확인할 점과 직업 정보 안내에만 씁니다. 나중에 입력해도 됩니다.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        st.markdown('<p class="optional-field-label">최종 학력</p>', unsafe_allow_html=True)
        education = st.selectbox(
            "최종 학력",
            ["미입력", "고졸", "전문학사", "학사", "석사 이상"],
            label_visibility="collapsed",
            key="context_education_select",
        )

    with st.container(border=True):
        st.markdown('<p class="optional-field-label">경력</p>', unsafe_allow_html=True)
        career = st.selectbox(
            "경력",
            ["미입력", "신입", "경험 있음"],
            label_visibility="collapsed",
            key="context_career_select",
        )

    with st.container(border=True):
        st.markdown('<p class="optional-field-label">희망 근무지역</p>', unsafe_allow_html=True)
        region = st.multiselect(
            "희망 근무지역",
            ["서울", "경기", "인천", "부산", "대구", "광주", "대전", "울산", "세종", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주", "상관없음"],
            label_visibility="collapsed",
            key="context_region_select",
        )

    with st.container(border=True):
        st.markdown('<p class="optional-field-label">업무 방식 선호도</p>', unsafe_allow_html=True)
        work_style = st.segmented_control(
            "업무 방식 선호도",
            ["미입력", "팀 작업 선호", "개인 작업 선호"],
            label_visibility="collapsed",
            key="context_work_style_select",
        )

    with st.container(horizontal=True):
        if st.button("이전", icon=":material/arrow_back:"):
            go("diagnose")
            st.rerun()
        if st.button("결과 보기", type="primary", icon=":material/insights:"):
            st.session_state.context = {
                "education": None if education == "미입력" else education,
                "career": None if career == "미입력" else career,
                "region": region,
                "work_style": None if work_style in {None, "미입력"} else work_style,
            }
            user_vector, _clusters = build_user_profile(questions_payload, st.session_state.responses)
            ranked = rank_job_families(user_vector, profiles_payload["job_families"])
            st.session_state.user_vector = user_vector
            st.session_state.recommendations = ranked
            go("result")
            st.rerun()

elif st.session_state.step == "result":
    st.markdown(
        """
        <div class="result-hero">
          <p class="result-hero-title">지금 더 탐색해 볼 직군</p>
          <p class="result-hero-sub">답변을 기준으로 우선 살펴볼 만한 TOP 5를 정리했어요.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.info(DISCLAIMER)
    if st.session_state.recommendations and st.session_state.recommendations[0].get("close_score"):
        st.warning("1위와 2위의 점수 차이가 작습니다. 단정하지 말고 두 직군을 함께 보세요.")

    if st.session_state.user_vector:
        profile = personality_profile(st.session_state.user_vector)
        with st.container(border=True):
            st.markdown(
                f'<p class="personality-panel-title">🧠 성향 요약 · {escape_html(profile["type"]["name"])}</p>',
                unsafe_allow_html=True,
            )
            render_personality_type_box(profile["type"]["description"], profile["type"]["combo_note"])

            st.markdown('<div class="personality-radar-box">', unsafe_allow_html=True)
            radar = pgo.Figure()
            radar.add_trace(
                pgo.Scatterpolar(
                    r=profile["radar"]["values"],
                    theta=profile["radar"]["axes"],
                    fill="toself",
                    name="내 프로파일",
                    line_color="#0b5cab",
                    fillcolor="rgba(11, 92, 171, 0.22)",
                )
            )
            radar.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 100], gridcolor="#d7e9ff")),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                showlegend=False,
                margin=dict(l=20, r=20, t=20, b=20),
            )
            st.plotly_chart(radar, use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)

            insight_cols = st.columns(2, gap="medium")
            with insight_cols[0]:
                render_personality_insight_box(
                    "strengths",
                    profile["strengths_heading"],
                    profile["strengths"],
                    "✨",
                )
            with insight_cols[1]:
                render_personality_insight_box(
                    "unfamiliar",
                    profile["growth_points_heading"],
                    profile["growth_points"],
                    "🌱",
                    profile["growth_points_note"],
                )

    for item in st.session_state.recommendations:
        explained = explain_recommendation(
            item, st.session_state.context, user_vector=st.session_state.user_vector
        )
        rank_style = RESULT_RANK_STYLES.get(
            item["rank"],
            {"emoji": "📌", "accent": "#0b5cab", "bg": "#ffffff"},
        )
        band_label = copy["result"]["band_labels"].get(item["band"], item["band"])

        st.markdown(
            f"""
            <div class="result-card" style="background: {rank_style['bg']}; border-color: {rank_style['accent']}55;">
            <div class="result-card-head">
                <span class="result-rank-badge">{rank_style['emoji']} {item['rank']}. {item['name']}</span>
                <span class="result-score-pill">{item['total']:.0f}/100</span>
            </div>
            <span class="result-band-chip" style="background:{rank_style['accent']}22;color:{rank_style['accent']};">
                {band_label}
            </span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        render_result_section(
            "reasons",
            copy["result"]["reasons_heading"],
            explained["reasons"],
            "💡",
        )

        render_result_section(
            "cautions",
            copy["result"]["cautions_heading"],
            explained["cautions"],
            "🚩",
        )

        render_result_section(
            "actions",
            copy["result"]["actions_heading"],
            explained["actions"],
            "🚀",
        )

        render_result_section(
            "growth",
            copy["result"]["growth_heading"],
            explained["growth"],
            "📈",
        )

        if explained["glossary"]:
            render_result_section(
                "glossary",
                copy["result"]["glossary_heading"],
                explained["glossary"],
                "📘",
            )

        if st.button(
            "연관 직업 보기",
            key=f"open_{item['job_family_id']}",
            icon=":material/work:",
            use_container_width=True,
        ):
            st.session_state.selected_job_id = item["job_family_id"]
            go("detail")
            st.rerun()

    with st.container(horizontal=True):
        if st.button("이전", icon=":material/arrow_back:"):
            go("context")
            st.rerun()
        if st.button("결과 피드백", icon=":material/rate_review:"):
            go("feedback")
            st.rerun()

elif st.session_state.step == "detail":
    selected = next(
        (item for item in st.session_state.recommendations if item["job_family_id"] == st.session_state.selected_job_id),
        None,
    )
    if selected is None:
        go("result")
        st.rerun()
    else:
        family = next(item for item in profiles_payload["job_families"] if item["job_family_id"] == selected["job_family_id"])
        detail = job_family_detail(selected["job_family_id"])
        st.markdown(
            f"""
            <div class="detail-hero">
              <p class="detail-hero-title">{escape_html(selected["name"])}</p>
              <p class="detail-hero-sub">{escape_html(family["description"])}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            """
            <div class="detail-section-title-box">
              <p class="detail-section-title">연관 직업</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        for occupation in detail["occupations"]:
            snapshot = occupation["snapshot_json"]
            typical_tasks = snapshot.get("typical_tasks") or []
            fit_hint = snapshot.get("fit_hint") or ""
            education_hint = snapshot.get("education_hint") or ""
            official_name = snapshot.get("official_name") or ""
            source = snapshot.get("source") or ""

            official_name_html = (
                f"<p class='detail-occupation-hint'>공식 직업명: {escape_html(official_name)}</p>"
                if official_name
                else ""
            )

            fit_html = (
                f"<p class='detail-occupation-hint'>🌿 {escape_html(fit_hint)}</p>"
                if fit_hint
                else ""
            )

            source_html = (
                f"<p class='detail-occupation-hint'>출처: {escape_html(source)}</p>"
                if source
                else ""
            )

            st.markdown(
                f"""
                <div class="detail-occupation-card">
                <p class="detail-occupation-name">✨ {escape_html(occupation["name"])}</p>
                {official_name_html}
                <p class="detail-occupation-summary">{escape_html(snapshot.get("summary", ""))}</p>
                <p class="detail-occupation-hint">• {escape_html(" · ".join(typical_tasks))}</p>
                {fit_html}
                <p class="detail-occupation-hint">📚 {escape_html(education_hint)}</p>
                {source_html}
                </div>
                """,
                unsafe_allow_html=True,
            )

            st.link_button(
                f"{occupation['name']} 직업정보 보러가기",
                occupation["source_url"],
                icon=":material/open_in_new:",
                use_container_width=True,
            )

        if st.button(
            "결과로 돌아가기",
            icon=":material/arrow_back:",
            type="primary",
            use_container_width=True,
        ):
            go("result")
            st.rerun()

elif st.session_state.step == "feedback":
    st.header("이 결과가 탐색에 도움이 됐나요?")
    st.write("점수를 고치기 위한 입력이 아니라, 제품 개선을 위한 피드백입니다.")
    helpful = st.segmented_control("도움 정도", ["도움 됨", "보통", "아님"])
    reason = st.selectbox(
        "한 줄 이유",
        ["선택 안 함", "이유가 이해됐다", "직군 설명이 구체적이다", "문항이 길다", "결과가 나와 다르게 느껴진다", "단정처럼 보였다"],
    )
    if st.button("보내기", type="primary", icon=":material/send:"):
        st.session_state.feedback = {"helpful": helpful, "reason": reason}
        st.success("기록했습니다. 개인 식별정보는 저장하지 않습니다.")
    if st.button("결과로 돌아가기", icon=":material/arrow_back:"):
        go("result")
        st.rerun()
