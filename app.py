import json
import random
from pathlib import Path

import plotly.graph_objects as pgo
import streamlit as st

import engine
from domain.branching import (
    CLUSTER_ORDER,
    common_sjt_questions,
    followup_questions_for_clusters,
    likert_questions,
    visible_question_queue,
)
from services.explainer import explain_recommendation
from services.personality import personality_profile

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
    st.session_state.setdefault("session_id", None)
    st.session_state.setdefault("heard", None)
    st.session_state.setdefault("prior_test", [])


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
    st.session_state.scroll_to_top = True


def _start_from_landing() -> None:
    st.session_state.session_id = engine.start_session()
    go("optional")


def _save_optional_and_continue() -> None:
    mbti = str(st.session_state.get("optional_mbti_select") or "모름 / 건너뛰기")
    enneagram = str(st.session_state.get("optional_enneagram_select") or "모름 / 건너뛰기")
    st.session_state.optional_traits = {
        "mbti": None if mbti.startswith("모름") else mbti,
        "enneagram": None if enneagram.startswith("모름") else enneagram,
    }
    session_id = st.session_state.get("session_id")
    if session_id:
        engine.save_prior_test(
            session_id,
            mbti=st.session_state.optional_traits["mbti"],
            enneagram=st.session_state.optional_traits["enneagram"],
        )
    go("diagnose")


def _compute_and_show_result() -> None:
    education = st.session_state.get("context_education_select")
    career = st.session_state.get("context_career_select")
    region = st.session_state.get("context_region_select") or []
    work_style = st.session_state.get("context_work_style_select")
    st.session_state.context = {
        "education": None if education in {None, "미입력"} else education,
        "career": None if career in {None, "미입력"} else career,
        "region": region,
        "work_style": None if work_style in {None, "미입력"} else work_style,
    }
    if not st.session_state.session_id:
        st.session_state.session_id = engine.start_session()
    result = engine.compute(
        st.session_state.session_id,
        responses=st.session_state.responses,
        context=st.session_state.context,
        optional_traits=st.session_state.optional_traits,
    )
    st.session_state.user_vector = result["user_vector"]
    st.session_state.recommendations = result["top"]
    st.session_state.heard = result["heard"]
    st.session_state.prior_test = result.get("prior_test") or []
    go("result")


def apply_scroll_to_top():
    """버튼 클릭 후 Streamlit이 스크롤 위치를 유지해서, 새 화면이 맨 아래부터 보이는 것을 막는다."""
    should_scroll = bool(st.session_state.pop("scroll_to_top", False))
    script = """
        <script>
        (function () {
          const go = () => {
            const target = document.getElementById("krn-page-top");
            if (target) {
              target.scrollIntoView({ block: "start", behavior: "auto" });
            }
            const nodes = document.querySelectorAll(
              '[data-testid="stAppViewContainer"], [data-testid="stMain"], [data-testid="stMainBlockContainer"], section.main, .stApp'
            );
            nodes.forEach((el) => {
              el.scrollTop = 0;
              if (el.scrollTo) el.scrollTo(0, 0);
            });
            window.scrollTo(0, 0);
            document.documentElement.scrollTop = 0;
            document.body.scrollTop = 0;
          };
          go();
          requestAnimationFrame(go);
          const started = Date.now();
          const timer = setInterval(() => {
            go();
            if (Date.now() - started > 1200) clearInterval(timer);
          }, 50);
        })();
        </script>
        """ if should_scroll else ""
    # 스크롤 스크립트 유무와 관계없이 같은 슬롯을 써서, 문항 전환 때 레이아웃이 밀리지 않게 한다.
    st.html(
        f'<div id="krn-scroll-script"></div>{script}',
        unsafe_allow_javascript=should_scroll,
    )


def diagnosis_question_total(questions_payload: dict) -> int:
    """후속 SJT가 나중에 붙더라도, 사용자에게는 처음부터 전체 문항 수를 고정해 보여준다."""
    base = len(likert_questions(questions_payload)) + len(common_sjt_questions(questions_payload))
    followup = len(followup_questions_for_clusters(questions_payload, CLUSTER_ORDER[:2]))
    return base + followup


ROUTE = [
    ("landing", "시작하기"),
    ("optional", "자기이해"),
    ("diagnose", "핵심 진단"),
    ("context", "현실 조건"),
    ("result", "결과 보기"),
]
ROUTE_INDEX = {
    "landing": 0,
    "optional": 1,
    "diagnose": 2,
    "context": 3,
    "result": 4,
    "detail": 4,
    "feedback": 4,
}


def route_index(step: str) -> int:
    return ROUTE_INDEX.get(step, 0)


def render_route_rail(step: str) -> None:
    idx = route_index(step)
    items = []
    for i, (_, label) in enumerate(ROUTE):
        cls = "done" if i < idx else ("now" if i == idx else "")
        items.append(f'<div class="{cls}">{escape_html(label)}</div>')
    st.markdown(
        f"""
        <div class="rail-brand"><span>✦</span> 잠재력 발견</div>
        <p class="rail-sub">한 걸음씩 밝히며<br/>다음 직군을 찾아갑니다</p>
        <div class="route">{"".join(items)}</div>
        """,
        unsafe_allow_html=True,
    )


def render_stage_bar(step: str, count_label: str) -> None:
    idx = route_index(step)
    bars = "".join('<i class="on"></i>' if i <= idx else "<i></i>" for i in range(5))
    _, stage_name = ROUTE[idx]
    st.markdown(
        f"""
        <div class="stage-bar">
          <span>{idx + 1:02d} / {escape_html(stage_name)}</span>
          <div class="stage-progress">{bars}</div>
          <b>{escape_html(count_label)}</b>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _select_choice(state_key: str, value: object, question_id: str | None, auto_submit: bool) -> None:
    st.session_state[state_key] = value
    if auto_submit and question_id is not None:
        st.session_state.responses[question_id] = value


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
            st.button(
                label,
                key=f"{state_key}_option_{idx}",
                width="stretch",
                type="primary" if selected == value else "secondary",
                on_click=_select_choice,
                args=(state_key, value, question_id, auto_submit),
            )
    return selected


@st.fragment
def diagnose_controls(current: dict, answer_key: str, answered_ids: list[str]) -> None:
    """선택지만 다시 그려서, 문항 전체를 깜빡이지 않게 한다."""
    with st.container(key="diagnose_choices", vertical_alignment="top", border=False):
        if current["type"] == "likert":
            likert_options = [
                (1, "전혀\n아니다"),
                (2, "아니다"),
                (3, "보통"),
                (4, "그렇다"),
                (5, "매우\n그렇다"),
            ]
            render_choice_grid(
                likert_options,
                state_key=answer_key,
                columns=5,
                question_id=current["question_id"],
            )
        else:
            sjt_options = [(option["option_id"], option["label"]) for option in current["options"]]
            render_choice_grid(
                sjt_options,
                state_key=answer_key,
                columns=2,
                question_id=current["question_id"],
            )
    picked = st.session_state.get(answer_key)

    with st.container(key="diagnose_nav"):
        nav_prev, nav_next = st.columns(2, gap="medium")
        with nav_prev:
            if st.button("이전", icon=":material/arrow_back:", width="stretch"):
                if answered_ids:
                    last_id = answered_ids[-1]
                    del st.session_state.responses[last_id]
                    st.session_state.pop(f"choice_{last_id}", None)
                else:
                    go("optional")
                st.session_state.scroll_to_top = True
                st.rerun(scope="app")
        with nav_next:
            if st.button(
                "다음",
                type="primary",
                icon=":material/arrow_forward:",
                width="stretch",
                disabled=picked is None,
            ):
                st.session_state.responses[current["question_id"]] = picked
                if st.session_state.session_id:
                    engine.answer(st.session_state.session_id, current["question_id"], picked)
                st.session_state.scroll_to_top = True
                st.rerun(scope="app")


def escape_html(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_result_section(kind: str, title: str, lines: list[str], icon: str, *, expanded: bool = False):
    if not lines:
        return
    items_html = "".join(f"<li>{escape_html(line)}</li>" for line in lines)
    with st.expander(f"{icon} {title}", expanded=expanded):
        st.markdown(
            f"""
            <div class="result-section-box {kind}">
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
    *,
    expanded: bool = False,
):
    items_html = "".join(f"<li>{escape_html(line)}</li>" for line in lines)
    note_html = f'<p class="personality-insight-note">{escape_html(note)}</p>' if note else ""
    with st.expander(f"{icon} {title}", expanded=expanded):
        st.markdown(
            f"""
            <div class="personality-insight-box {kind}">
              {note_html}
              <ul class="personality-insight-list">{items_html}</ul>
            </div>
            """,
            unsafe_allow_html=True,
        )


st.set_page_config(
    page_title="잠재력 발견",
    page_icon=":material/explore:",
    layout="wide",
    initial_sidebar_state="expanded",
)
init_state()


@st.cache_resource
def _boot_engine():
    return engine.bootstrap()


_boot_engine()
questions_payload = load_json("questions.json")
profiles_payload = load_json("job_profiles.json")
likert_labels = questions_payload["likert_labels"]
copy = load_json("copy.json")
SCREEN = copy["screens"]
current_step = st.session_state.step
DAWN_STEPS = {"result", "detail", "feedback"}

st.html(f"<style>{(ROOT / 'static' / 'flow.css').read_text(encoding='utf-8')}</style>")
st.markdown(
    f'<div id="krn-skin" class="{"flow-dawn" if current_step in DAWN_STEPS else "flow-night"}"></div>',
    unsafe_allow_html=True,
)

st.markdown('<div id="krn-page-top"></div>', unsafe_allow_html=True)
apply_scroll_to_top()

with st.sidebar:
    render_route_rail(current_step)
    st.markdown('<div class="rail-reset-spacer"></div>', unsafe_allow_html=True)
    if st.button("처음부터 다시", icon=":material/refresh:"):
        reset_session()
        st.rerun()

if st.session_state.step == "landing":
    render_stage_bar("landing", "약 10분")
    copy_col, light_col = st.columns([1.45, 0.75], gap="large", vertical_alignment="center")
    with copy_col:
        st.markdown(
            f"""
            <div class="landing-hero">
              <div class="landing-chip">취업 탐색 가이드</div>
              <div class="landing-title">
                <span>지금의 나에게 맞는 직군을</span>
                <span>명확하게 좁혀보세요</span>
              </div>
              <p class="landing-subtitle">{escape_html(SCREEN["landing_first_line"])}</p>
              <p class="landing-subtitle landing-subtitle-sub">
                약 10분 동안 흥미·업무 방식·상황 판단에 답하면,
                8개 대분류 직군 중 상대적으로 가까운 TOP 5를 보여드립니다.
              </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with light_col:
        st.markdown(
            """
            <div class="lantern">
              <div>
                <b>✦</b>
                <span>한 문항씩 답을 고를수록, 앞이 조금 더 선명해집니다</span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.space("large")
    st.markdown(
        f"""
        <div class="landing-disclaimer-box">
        <p class="landing-disclaimer-text">{escape_html(DISCLAIMER)}</p>
        </div>
        <p class="landing-note">결과는 합격 가능성·능력 판정이 아닌, 탐색 우선순위 안내입니다.</p>
        """,
        unsafe_allow_html=True,
    )
    st.space("medium")
    st.markdown(
        """
        <p class="landing-consent-heading">아래 내용을 확인한 뒤 체크하고 탐색을 시작해 주세요.</p>
        """,
        unsafe_allow_html=True,
    )
    with st.container(horizontal=True, horizontal_alignment="left", gap=None):
        st.checkbox(
            "안내를 확인했고, 결과가 합격·능력 판정이 아님을 이해합니다.",
            key="consent",
            width="stretch",
        )

    st.space("medium")
    st.button(
        SCREEN["start_button"],
        type="primary",
        icon=":material/play_arrow:",
        disabled=not st.session_state.consent,
        width="stretch",
        on_click=_start_from_landing,
    )

elif st.session_state.step == "optional":
    render_stage_bar("optional", "선택")
    st.markdown(
        '<div class="page-section-chip">기존 자기 이해 정보</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="optional-note-box">
          <p class="optional-note-text">
            선택 입력입니다. 모르면 건너뛰어도 됩니다. 직군 점수·순위에는 넣지 않고, 결과에서 1위 직군을 읽을 때 참고 렌즈로만 씁니다.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.space("medium")
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
        st.markdown('<p class="optional-field-label">에니어그램</p>', unsafe_allow_html=True)
        enneagram = st.selectbox(
            "에니어그램",
            enneagram_options,
            index=enneagram_options.index(str(enneagram_default)) if enneagram_default in enneagram_options else 0,
            label_visibility="collapsed",
            key="optional_enneagram_select",
        )

    st.space("medium")
    with st.container(horizontal=True):
        st.button("이전", icon=":material/arrow_back:", on_click=go, args=("landing",))
        st.button(
            "다음",
            type="primary",
            icon=":material/arrow_forward:",
            on_click=_save_optional_and_continue,
        )

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
    halfway = answered_count >= total_questions / 2
    orbit_note = SCREEN["mid_encourage"] if halfway else SCREEN["skip_hint"]

    render_stage_bar("diagnose", f"{step_no:02d} / {total_questions:02d}")
    st.html(
        f"""
        <div class="question-block">
          <p class="kicker">STEP {step_no:02d} · {escape_html(module_label)}</p>
          <div class="diagnose-prompt-box">{escape_html(current["prompt"])}</div>
          <div class="orbit" aria-hidden="true"><span>✦</span><small>{escape_html(orbit_note)}</small></div>
        </div>
        """
    )
    diagnose_controls(current, answer_key, answered_ids)

elif st.session_state.step == "context":
    render_stage_bar("context", "선택")
    st.markdown('<div class="page-section-chip">추가 정보 입력</div>', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="optional-note-box">
          <p class="optional-note-text">추천 점수에는 더하지 않습니다. 결과의 확인할 점과 직업 정보 안내에만 씁니다. 나중에 입력해도 됩니다.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.space("medium")
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

    st.space("medium")
    with st.container(horizontal=True):
        st.button("이전", icon=":material/arrow_back:", on_click=go, args=("diagnose",))
        st.button(
            "결과 보기",
            type="primary",
            icon=":material/wb_sunny:",
            on_click=_compute_and_show_result,
        )

elif st.session_state.step == "result":
    render_stage_bar("result", "완료")
    recs = st.session_state.recommendations or []
    top_name = recs[0]["name"] if recs else "이 직군"
    rank_tiles = []
    for item in recs[:5]:
        cls = " first" if item["rank"] == 1 else ""
        rank_tiles.append(
            f'<span class="{cls.strip()}">{item["rank"]:02d}<br/>{escape_html(item["name"])}</span>'
        )

    st.markdown(
        f"""
        <div class="result-hero">
          <p class="kicker">{escape_html(SCREEN["result_top"])}</p>
          <p class="result-hero-title"><span>여기서부터</span><span>실제로 들여다보면 돼요</span></p>
          <p class="result-hero-sub">답변을 기준으로 우선 살펴볼 만한 TOP 5를 정리했어요.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if rank_tiles:
        st.markdown(f'<div class="rank-strip">{"".join(rank_tiles)}</div>', unsafe_allow_html=True)
    st.space("medium")
    st.markdown(
        f"""
        <div class="dawn-next">
          <h3>{escape_html(copy["result"]["actions_heading"])}</h3>
          <p>{escape_html(top_name)} 공고와 하루 업무를 한 번만 구체적으로 열어 보세요. 점수를 더 보는 것보다, 실제 일을 보는 쪽이 다음 한 걸음입니다.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.space("medium")
    st.markdown(
        f'<div class="dawn-notice">{escape_html(DISCLAIMER)}</div>',
        unsafe_allow_html=True,
    )
    if st.session_state.get("heard"):
        heard = st.session_state.heard
        contrast_html = (
            f'<p class="personality-type-note">{escape_html(heard["contrast"])}</p>'
            if heard.get("contrast")
            else ""
        )
        st.markdown(
            f"""
            <div class="personality-type-box">
              <p class="personality-type-desc">{escape_html(heard["headline"])}</p>
              {contrast_html}
            </div>
            """,
            unsafe_allow_html=True,
        )
    if st.session_state.get("prior_test"):
        items = "".join(f"<li>{escape_html(line)}</li>" for line in st.session_state.prior_test)
        st.markdown(
            f"""
            <div class="personality-type-box">
              <p class="personality-type-desc">기존 자기 이해 정보</p>
              <ul class="personality-insight-list">{items}</ul>
            </div>
            """,
            unsafe_allow_html=True,
        )
    if st.session_state.recommendations and st.session_state.recommendations[0].get("close_score"):
        st.markdown(
            '<div class="dawn-notice dawn-notice-soft">1위와 2위의 점수 차이가 작습니다. 단정하지 말고 두 직군을 함께 보세요.</div>',
            unsafe_allow_html=True,
        )

    if st.session_state.user_vector:
        profile = personality_profile(st.session_state.user_vector)
        with st.container(border=True):
            st.markdown(
                f'<p class="personality-panel-title">🧠 성향 요약 · {escape_html(profile["type"]["name"])}</p>',
                unsafe_allow_html=True,
            )
            render_personality_type_box(profile["type"]["description"], profile["type"]["combo_note"])

            radar = pgo.Figure()
            radar.add_trace(
                pgo.Scatterpolar(
                    r=profile["radar"]["values"],
                    theta=profile["radar"]["axes"],
                    fill="toself",
                    name="내 프로파일",
                    line_color="#c4923a",
                    fillcolor="rgba(225, 178, 97, 0.32)",
                )
            )
            radar.update_layout(
                font=dict(color="#18344b", size=12),
                polar=dict(
                    bgcolor="rgba(255, 253, 248, 0.55)",
                    radialaxis=dict(
                        visible=True,
                        range=[0, 100],
                        gridcolor="#d4c4a0",
                        linecolor="#8a7350",
                        tickfont=dict(color="#18344b", size=11),
                    ),
                    angularaxis=dict(
                        gridcolor="#d4c4a0",
                        linecolor="#8a7350",
                        tickfont=dict(color="#18344b", size=12),
                    ),
                ),
                paper_bgcolor="rgba(255, 253, 248, 0.92)",
                plot_bgcolor="rgba(0,0,0,0)",
                showlegend=False,
                margin=dict(l=90, r=90, t=48, b=48),
                height=520,
            )
            st.plotly_chart(
                radar,
                width="stretch",
                theme=None,
                config={"displayModeBar": False},
            )

            render_personality_insight_box(
                "strengths",
                profile["strengths_heading"],
                profile["strengths"],
                "✨",
                expanded=True,
            )
            render_personality_insight_box(
                "unfamiliar",
                profile["growth_points_heading"],
                profile["growth_points"],
                "🌱",
                profile["growth_points_note"],
                expanded=False,
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
            <span class="result-band-chip">{band_label}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        looking_at = item["rank"] == 1
        with st.expander("직군 설명 보기", expanded=looking_at):
            render_result_section(
                "reasons",
                copy["result"]["reasons_heading"],
                explained["reasons"],
                "💡",
                expanded=looking_at,
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
            width="stretch",
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
        render_stage_bar("result", "완료")
        family = next(item for item in profiles_payload["job_families"] if item["job_family_id"] == selected["job_family_id"])
        detail = engine.get_family_detail(selected["job_family_id"], st.session_state.session_id)
        st.markdown(
            f"""
            <div class="detail-hero">
              <p class="detail-kicker">추천 직군</p>
              <p class="detail-hero-title">{escape_html(selected["name"])}</p>
              <p class="detail-hero-sub">{escape_html(family["description"])}</p>
            </div>
            <p class="detail-section-title">연관 직업</p>
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
                if source and "팀 검수 스냅샷" not in source
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
                width="stretch",
            )

        if st.button(
            "결과로 돌아가기",
            icon=":material/arrow_back:",
            type="primary",
            width="stretch",
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
        if st.session_state.session_id:
            engine.save_feedback(st.session_state.session_id, helpful, reason)
        st.success("기록했습니다. 개인 식별정보는 저장하지 않습니다.")
    if st.button("결과로 돌아가기", icon=":material/arrow_back:"):
        go("result")
        st.rerun()
