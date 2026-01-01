import os
import json
import base64
from pathlib import Path
from datetime import datetime

import re

import streamlit as st
#from dotenv import load_dotenv
from openai import OpenAI

def safe_json_parse(text: str) -> dict | None:
    """
    모델 출력에서 JSON 객체만 안전하게 추출해서 파싱.
    실패하면 None 반환.
    """
    if not text:
        return None

    # 1) 전체가 JSON인 경우
    try:
        return json.loads(text)
    except Exception:
        pass

    # 2) 중간에 섞인 경우 → 첫 { ... } 블록 추출
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None

    try:
        return json.loads(match.group())
    except Exception:
        return None

client = OpenAI()  # OPENAI_API_KEY를 자동으로 읽음 :contentReference[oaicite:3]{index=3}

# -----------------------------
# 1) 파일 경로(저장 위치) 설정
# -----------------------------
PROFILE_PATH = Path("user_profile.json")
MEALS_DIR = Path("meals")
LOG_PATH = Path("meals_log.json")

# -----------------------------
# 2) 프로필(건강정보) 불러오기/저장하기
# -----------------------------
def load_profile() -> dict:
    if PROFILE_PATH.exists():
        try:
            return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_profile(profile: dict) -> None:
    PROFILE_PATH.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

# -----------------------------
# 3) 로그 불러오기/추가하기
# -----------------------------
def load_log() -> list:
    if LOG_PATH.exists():
        try:
            return json.loads(LOG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def append_log(entry: dict) -> None:
    log = load_log()
    log.append(entry)
    LOG_PATH.write_text(
        json.dumps(log, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

# -----------------------------
# 4) 이미지 -> base64 data URL 변환
# -----------------------------
def to_data_url(file_bytes: bytes, mime: str) -> str:
    b64 = base64.b64encode(file_bytes).decode("utf-8")
    return f"data:{mime};base64,{b64}"

# -----------------------------
# 5) AI 분석 함수 (사진 + 프로필 + 이전요약)
# -----------------------------

def analyze_meal(image_bytes: bytes, mime: str, profile: dict, prev_summary: str | None) -> dict:
    """
    반환 dict:
    {
      "foods": [...],
      "macros": {"carbs_g":"...", "protein_g":"...", "fat_g":"...", "calories_kcal":"..."},
      "diagnosis": "...",
      "next_meal_tip": "..."
    }
    """
    data_url = to_data_url(image_bytes, mime)

    # “정확도”보다 “쓸만함”이 목적이라 범위/추정으로 요구
    system = (
         "너는 식사 사진 기반 영양 추정 코치다. "
        "반드시 JSON 객체만 출력해야 한다. "
        "설명, 문장, 코드블록(```)을 절대 포함하지 마라. "
        "값은 모두 문자열로 작성하라. "
        "정확한 계량은 불가능하므로 '추정'임을 전제로 범위로 답하라."
    )

    user_text = f"""
사용자 프로필:
- 키(cm): {profile.get("height")}
- 몸무게(kg): {profile.get("weight")}
- 성별: {profile.get("gender")}
- 목표: {profile.get("goal")}  (maintain=유지, cut=감량, bulk=증량)

이전 식사 요약(있으면 참고):
{prev_summary or "없음"}

요청:
아래 스키마를 정확히 따르는 JSON만 출력하라.
{{
  "foods": ["string"],
  "macros": {{
    "carbs_g": "min~max",
    "protein_g": "min~max",
    "fat_g": "min~max",
    "calories_kcal": "min~max"
  }},
  "diagnosis": "string",
  "next_meal_tip": "string"
}}
"""

    # OpenAI 문서의 이미지 입력 형식: input_text + input_image :contentReference[oaicite:4]{index=4}
    for attempt in range(2):  # 최대 2번 시도
        resp = client.responses.create(
            model="gpt-4.1-mini",
            input=[{
                "role": "system",
                "content": [{"type": "input_text", "text": system}],
            },{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": user_text},
                    {"type": "input_image", "image_url": data_url},
                ],
            }],
        )

        raw_text = resp.output_text.strip()
        parsed = safe_json_parse(raw_text)

        if parsed:
            return parsed

        # 재시도 시 프롬프트 더 강하게
        user_text = (
            "이전 출력이 JSON 형식이 아니었다. "
            "설명 없이 JSON 객체만 다시 출력하라.\n\n" + user_text
        )

    # 2번 실패 → fallback
    return {
        "foods": [],
        "macros": {
            "carbs_g": "추정 불가",
            "protein_g": "추정 불가",
            "fat_g": "추정 불가",
            "calories_kcal": "추정 불가"
        },
        "diagnosis": "사진 인식이 불명확해 영양 추정이 어려움.",
        "next_meal_tip": "조금 더 가까이서 다시 찍어보세요."

    }

# -----------------------------
# 6) Streamlit 페이지
# -----------------------------
st.set_page_config(page_title="Meal Agent MVP", layout="centered")
st.title("🍽️ Meal Agent MVP")

# 세션 상태(이전 식사 요약) 초기화
if "prev_summary" not in st.session_state:
    st.session_state.prev_summary = None

# -----------------------------
# 7) 프로필 섹션
# -----------------------------
st.header("1) 내 건강 정보 저장")
profile = load_profile()

with st.form("profile_form"):
    st.subheader("프로필 입력")
    height = st.number_input("키 (cm)", min_value=100, max_value=220, value=int(profile.get("height", 175)))
    weight = st.number_input("몸무게 (kg)", min_value=30, max_value=200, value=int(profile.get("weight", 70)))
    gender = st.selectbox("성별", ["male", "female", "other"],
                          index=["male","female","other"].index(profile.get("gender","male"))
                          if profile.get("gender","male") in ["male","female","other"] else 0)
    goal = st.selectbox("목표", ["maintain", "cut", "bulk"],
                        index=["maintain","cut","bulk"].index(profile.get("goal","maintain"))
                        if profile.get("goal","maintain") in ["maintain","cut","bulk"] else 0)
    submitted = st.form_submit_button("저장")

if submitted:
    new_profile = {"height": int(height), "weight": int(weight), "gender": gender, "goal": goal}
    save_profile(new_profile)
    st.success("저장 완료! user_profile.json에 기록했어.")
    profile = new_profile

#st.caption("현재 저장된 프로필")
#st.json(profile if profile else {"info": "아직 저장된 프로필이 없어."})
#st.divider()

# -----------------------------
# 8) 사진 업로드 + AI 분석
# -----------------------------
st.header("2) 식사 사진 업로드 & 분석")

uploaded = st.file_uploader("식사 사진을 올려줘 (jpg/png)", type=["jpg", "jpeg", "png"])

if uploaded is None:
    st.info("사진을 올리면 분석 버튼이 생겨.")
else:
    st.image(uploaded, caption="업로드한 식사 사진", use_container_width=True)

    # mime 추정
    mime = uploaded.type or "image/jpeg"
    img_bytes = uploaded.getvalue()

    col1, col2 = st.columns(2)
    with col1:
        run = st.button("“사진 분석 (3초 정도 걸려요)”")
    # 8-1) AI 분석
    if run:
        if not profile:
            st.error("먼저 프로필(키/몸무게/성별/목표)을 저장해줘.")
        else:
            try:
                with st.spinner("분석 중..."):
                    
                    result = analyze_meal(
                        image_bytes=img_bytes,
                        mime=mime,
                        profile=profile,
                        prev_summary=st.session_state.prev_summary
                    )
                entry = {
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "foods": result.get("foods", []),
                    "macros": result.get("macros", {}),
                    "diagnosis": result.get("diagnosis", ""),
                    "next_meal_tip": result.get("next_meal_tip", ""),
                    "note": "auto_log_no_image"
                }
                append_log(entry)

                st.subheader("✅ 분석 결과(추정)")
                #st.json(result)
                macros = result.get("macros", {})

                st.markdown(f"""
                    ### 🍽️ 오늘 식사 요약
                    - 음식: {", ".join(result.get("foods", [])[:3]) or "알 수 없음"}
                    - 탄수화물: {macros.get("carbs_g", "-")} g
                    - 단백질: {macros.get("protein_g", "-")} g
                    - 지방: {macros.get("fat_g", "-")} g
                    - 칼로리: {macros.get("calories_kcal", "-")} kcal

                    👉 **진단:** {result.get("diagnosis", "")}  
                    👉 **다음 끼니 팁:** {result.get("next_meal_tip", "")}
                    """)


                # 다음 분석에 쓸 “이전 요약 1줄” 만들기
                # (AI 에이전트 느낌 최소 장치)
                foods = ", ".join(result.get("foods", [])[:3])
                st.session_state.prev_summary = f"{foods} / 진단: {result.get('diagnosis','')}"
                st.caption(f"다음 분석에 참고할 이전 요약(세션): {st.session_state.prev_summary}")

            except json.JSONDecodeError:
                st.error("모델 출력이 JSON 형식이 아니었어. 다시 눌러봐(가끔 발생).")
            except Exception as e:
                st.error(f"분석 실패: {e}")

st.divider()

# -----------------------------
# 9) 최근 로그 보기
# -----------------------------
st.header("3) 최근 기록 보기")

st.header("최근 식사 기록 (최대 5개)")
log = load_log()
if not log:
    st.write("아직 저장된 기록이 없어.")
else:
    for item in log[-5:][::-1]:
        foods = ", ".join(item.get("foods", [])[:3])
        st.markdown(f"""
- 🕒 {item.get("timestamp")}
- 🍽️ {foods}
- 🧠 {item.get("diagnosis","")}
- ✅ 팁: {item.get("next_meal_tip","")}
""")
