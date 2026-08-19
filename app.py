import json
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


def render_choice_grid(options: list[tuple[object, str]], state_key: str, columns: int = 3):
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
                st.rerun()
    return selected


st.set_page_config(page_title="잠재력 발견", page_icon=":material/explore:", layout="centered")
init_state()
questions_payload = load_json("questions.json")
profiles_payload = load_json("job_profiles.json")
likert_labels = questions_payload["likert_labels"]

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
        margin: 0;
    }
    .landing-kpi-box {
        background: #ffffff;
        border: 1px solid #d7e9ff;
        border-radius: 14px;
        padding: 16px 14px;
        margin-bottom: 10px;
        text-align: center;
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
    div[data-testid="stCheckbox"] > label {
        background: #f7fbff;
        border: 1px solid #d7e9ff;
        border-radius: 12px;
        padding: 10px 12px;
        width: 100%;
    }
    div[data-testid="stCheckbox"] p {
        font-size: 20px;
        font-weight: 800;
        color: #123a66;
        line-height: 1.35;
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
    </style>
    """,
    unsafe_allow_html=True,
)

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

    st.info(DISCLAIMER)
    st.markdown('<p class="landing-note">결과는 합격 가능성·능력 판정이 아닌, 탐색 우선순위 안내입니다.</p>', unsafe_allow_html=True)
    st.write("")
    st.checkbox("안내를 확인했고, 결과가 합격·능력 판정이 아님을 이해합니다.", key="consent")
    st.button(
        "진단 시작",
        type="primary",
        icon=":material/play_arrow:",
        disabled=not st.session_state.consent,
        on_click=go,
        args=("optional",),
    )

elif st.session_state.step == "optional":
    st.markdown('<div class="page-section-chip">기존 자기 이해 정보</div>', unsafe_allow_html=True)
    st.write("선택 입력입니다. 모르면 건너뛰어도 되고, 직군 점수에는 반영되지 않습니다.")
    mbti = st.selectbox(
        "MBTI",
        ["모름 / 건너뛰기", "ISTJ", "ISFJ", "INFJ", "INTJ", "ISTP", "ISFP", "INFP", "INTP", "ESTP", "ESFP", "ENFP", "ENTP", "ESTJ", "ESFJ", "ENFJ", "ENTJ"],
    )
    enneagram = st.selectbox(
        "애니어그램",
        ["모름 / 건너뛰기", "1", "2", "3", "4", "5", "6", "7", "8", "9"],
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
    queue = visible_question_queue(questions_payload, st.session_state.responses)
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
    st.markdown('<div class="page-section-chip">답변 진행률</div>', unsafe_allow_html=True)
    st.progress(min(1.0, answered_count / max(total_questions, 1)))
    st.caption(f"{answered_count} / {total_questions}문항 · 한 문항에는 한 가지만 묻습니다.")

    if current is None:
        go("context")
        st.rerun()
    else:
        step_no = answered_count + 1
        st.caption(f"STEP {step_no:02d} / {total_questions:02d}")
        module_label = module_labels.get(current.get("module", ""), "진단 문항")
        st.markdown(f'<div class="diagnose-module-chip">{module_label}</div>', unsafe_allow_html=True)
        st.write(current["prompt"])
        answer_key = f"choice_{current['question_id']}"
        if current["type"] == "likert":
            likert_display = {
                5: "매우 그렇다",
                4: "그렇다",
                3: "보통이다",
                2: "아니다",
                1: "전혀 아니다",
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
                columns=1,
            )
        else:
            sjt_options = [(option["option_id"], option["label"]) for option in current["options"]]
            choice = render_choice_grid(
                sjt_options,
                state_key=answer_key,
                columns=2 if len(sjt_options) <= 4 else 3,
            )

        with st.container(horizontal=True):
            if st.button("이전", icon=":material/arrow_back:"):
                if answered_ids:
                    del st.session_state.responses[answered_ids[-1]]
                else:
                    go("optional")
                st.rerun()
            if st.button("다음", type="primary", icon=":material/arrow_forward:", disabled=choice is None):
                st.session_state.responses[current["question_id"]] = choice
                st.rerun()

elif st.session_state.step == "context":
    st.header("현실 조건")
    st.write("추천 점수에는 더하지 않습니다. 결과의 확인할 점과 직업 정보 안내에만 씁니다. 나중에 입력해도 됩니다.")
    education = st.selectbox("최종 학력", ["미입력", "고졸", "전문학사", "학사", "석사 이상"])
    career = st.selectbox("경력", ["미입력", "신입", "경험 있음"])
    region = st.multiselect("희망 근무지역", ["서울", "경기", "인천", "부산", "대구", "광주", "대전", "울산", "세종", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주", "상관없음"])
    work_style = st.segmented_control("업무 방식 선호", ["미입력", "팀 작업 선호", "개인 작업 선호"])
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
    st.header("지금 더 탐색해 볼 직군")
    st.info(DISCLAIMER)
    if st.session_state.recommendations and st.session_state.recommendations[0].get("close_score"):
        st.warning("1위와 2위의 점수 차이가 작습니다. 단정하지 말고 두 직군을 함께 보세요.")

    if st.session_state.user_vector:
        profile = personality_profile(st.session_state.user_vector)
        with st.container(border=True):
            st.subheader(f"성향 요약 · {profile['type']['name']}")
            st.write(profile["type"]["description"])
            radar = pgo.Figure()
            radar.add_trace(
                pgo.Scatterpolar(
                    r=profile["radar"]["values"],
                    theta=profile["radar"]["axes"],
                    fill="toself",
                    name="내 프로파일",
                )
            )
            radar.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                showlegend=False,
                margin=dict(l=20, r=20, t=20, b=20),
            )
            st.plotly_chart(radar, use_container_width=True)
            col_strength, col_growth = st.columns(2)
            with col_strength:
                st.write(f"**{profile['strengths_heading']}**")
                for line in profile["strengths"]:
                    st.write(f"- {line}")
            with col_growth:
                st.write(f"**{profile['growth_points_heading']}**")
                st.caption(profile["growth_points_note"])
                for line in profile["growth_points"]:
                    st.write(f"- {line}")

    for item in st.session_state.recommendations:
        explained = explain_recommendation(item, st.session_state.context)
        with st.container(border=True):
            st.subheader(f"{item['rank']}. {item['name']}")
            st.metric("현재 프로파일 기준 상대 적합도", f"{item['total']:.0f}/100")
            st.caption(item["band"])
            st.write("왜 이 직군을 더 볼까요?")
            for line in explained["reasons"]:
                st.write(f"- {line}")
            st.write("무엇을 확인할까요?")
            for line in explained["cautions"]:
                st.write(f"- {line}")
            if st.button("연관 직업 보기", key=f"open_{item['job_family_id']}", icon=":material/work:"):
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
        st.header(selected["name"])
        st.write(family["description"])
        st.caption(f"출처: {detail['source_label']}")
        st.write("이 분류는 통계·자격 판정용 공식 분류를 그대로 복제한 것이 아닙니다.")
        st.subheader("연관 직업")
        for occupation in detail["occupations"]:
            snapshot = occupation["snapshot_json"]
            with st.container(border=True):
                st.write(f"**{occupation['name']}**")
                st.write(snapshot["summary"])
                st.caption(" · ".join(snapshot["typical_tasks"]))
                if snapshot.get("fit_hint"):
                    st.write(snapshot["fit_hint"])
                st.caption(snapshot["education_hint"])
                st.link_button("직업정보 보러가기", occupation["source_url"], icon=":material/open_in_new:")
        if st.button("결과로 돌아가기", icon=":material/arrow_back:"):
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
