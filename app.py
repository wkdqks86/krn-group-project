import json
from pathlib import Path

import streamlit as st

from domain.branching import build_user_profile, visible_question_queue
from domain.scoring import ENGINE_VERSION, rank_job_families
from services.explainer import explain_recommendation
from services.work24 import job_family_detail

ROOT = Path(__file__).resolve().parent
DISCLAIMER = (
    "이 결과는 취업 성공 가능성이나 능력을 판정하지 않습니다. "
    "현재 입력한 프로파일과 각 직군의 초기 요구 프로파일 사이의 상대적 적합도를 보여주는 탐색 가이드입니다."
)
STEPS = ["landing", "optional", "diagnose", "context", "result", "detail", "feedback"]


@st.cache_data
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


st.set_page_config(page_title="잠재력 발견", page_icon=":material/explore:", layout="centered")
init_state()
questions_payload = load_json("questions.json")
profiles_payload = load_json("job_profiles.json")
likert_labels = questions_payload["likert_labels"]

st.title("잠재력 발견")
st.caption(f"20~30대 취업준비생을 위한 직군 탐색 MVP · engine {ENGINE_VERSION}")

with st.sidebar:
    st.subheader("진행")
    st.write(f"현재 단계: {st.session_state.step}")
    if st.button("처음부터 다시", icon=":material/refresh:"):
        reset_session()
        st.rerun()

if st.session_state.step == "landing":
    st.header("지금 더 탐색해 볼 직군을 좁혀 보세요")
    st.write("약 10분 동안 흥미·업무 방식·상황 판단에 답하면, 8개 대분류 직군 중 상대적으로 가까운 TOP 5를 보여 줍니다.")
    st.info(DISCLAIMER)
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
    st.header("이미 아는 자기이해 정보")
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
    st.header("핵심 진단")
    st.progress(min(1.0, len(answered_ids) / max(len(queue), 1)))
    st.caption(f"{len(answered_ids)} / 약 {len(queue)}문항 · 한 문항에는 한 가지만 묻습니다.")

    if current is None:
        go("context")
        st.rerun()
    else:
        st.write(current["prompt"])
        answer_key = f"widget_{current['question_id']}"
        if current["type"] == "likert":
            choice = st.radio(
                "응답",
                options=[1, 2, 3, 4, 5],
                format_func=lambda value: f"{value}. {likert_labels[value - 1]}",
                index=None,
                key=answer_key,
            )
        else:
            options = {option["label"]: option["option_id"] for option in current["options"]}
            label = st.radio("선택지", options=list(options.keys()), index=None, key=answer_key)
            choice = options.get(label) if label else None

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
