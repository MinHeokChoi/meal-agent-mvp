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

def parse_range_min_max(range_str: str) -> tuple[float | None, float | None]:
    """
    "min~max"에서 min,max 숫자 추출. 없으면 (None, None)
    """
    if not range_str or "불가" in range_str:
        return (None, None)
    nums = re.findall(r"[\d.]+", str(range_str))
    if not nums:
        return (None, None)
    try:
        if len(nums) == 1:
            v = float(nums[0])
            return (v, v)
        return (float(nums[0]), float(nums[-1]))
    except Exception:
        return (None, None)

def add_ranges(a: str, b: str) -> str:
    """
    범위 문자열 두 개를 더해 "min~max"로 반환.
    하나라도 추정 불가면 '추정 불가'
    """
    amin, amax = parse_range_min_max(a)
    bmin, bmax = parse_range_min_max(b)
    if amin is None or amax is None or bmin is None or bmax is None:
        return "추정 불가"
    return f"{int(round(amin + bmin))}~{int(round(amax + bmax))}"

def daily_totals(date_iso: str) -> dict:
    """
    특정 날짜(YYYY-MM-DD)의 누적 macros 범위를 합산해 반환
    """
    log = load_log()
    items = [x for x in log if x.get("date") == date_iso]

    total = {
        "carbs_g": "0~0",
        "protein_g": "0~0",
        "fat_g": "0~0",
        "calories_kcal": "0~0",
    }

    for it in items:
        macros = it.get("macros", {}) or {}
        total["carbs_g"] = add_ranges(total["carbs_g"], str(macros.get("carbs_g", "추정 불가")))
        total["protein_g"] = add_ranges(total["protein_g"], str(macros.get("protein_g", "추정 불가")))
        total["fat_g"] = add_ranges(total["fat_g"], str(macros.get("fat_g", "추정 불가")))
        total["calories_kcal"] = add_ranges(total["calories_kcal"], str(macros.get("calories_kcal", "추정 불가")))

    return {"count": len(items), "total_macros": total, "items": items}

def get_daily_targets(profile: dict) -> dict:
    weight = profile.get("weight")
    goal = (profile.get("goal") or "maintain").lower()
    if not isinstance(weight, (int, float)) or weight <= 0:
        weight = 70

    if goal == "bulk":
        protein = weight * 1.8
        cal = 2700
    elif goal == "cut":
        protein = weight * 1.6
        cal = 2000
    else:
        protein = weight * 1.6
        cal = 2300

    return {
        "protein_g": f"{int(round(protein*0.9))}~{int(round(protein*1.1))}",
        "calories_kcal": f"{int(round(cal*0.9))}~{int(round(cal*1.1))}",
    }

def render_today_dashboard(profile: dict):
    st.header("📊 오늘 누적(추정)")
    today = datetime.now().date().isoformat()
    tot = daily_totals(today)
    tm = tot["total_macros"]

    targets = get_daily_targets(profile) if profile else {}

    st.markdown(f"""
- 오늘 기록된 끼니 수: **{tot["count"]}**
- 누적 탄수화물: **{tm["carbs_g"]} g**
- 누적 단백질: **{tm["protein_g"]} g** / 목표(대략): **{targets.get("protein_g","-")} g**
- 누적 지방: **{tm["fat_g"]} g**
- 누적 칼로리: **{tm["calories_kcal"]} kcal** / 목표(대략): **{targets.get("calories_kcal","-")} kcal**
""")

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

def get_default_meal_type() -> str:
    """
    최근 로그의 meal_type을 기본값으로 반환.
    없으면 '점심'
    """
    log = load_log()
    if not log:
        return "점심"
    last = log[-1].get("meal_type")
    return last if last in ["아침", "점심", "저녁", "간식"] else "점심"

def make_prev_summary_from_log(n: int = 3) -> str | None:
    """
    최근 n개 식사 기록을 한 줄 요약으로 만들어 반환.
    기록이 없으면 None.
    """
    log = load_log()
    if not log:
        return None

    recent = log[-n:]  # 오래된→최신 순
    lines = []
    for item in recent:
        foods = ", ".join(item.get("foods", [])[:3]) or "음식 불명"
        diag = (item.get("diagnosis") or "").strip()
        tip = (item.get("next_meal_tip") or "").strip()

        # 너무 길면 잘라서 프롬프트 비용/노이즈 줄이기
        if len(diag) > 80:
            diag = diag[:80] + "..."
        if len(tip) > 60:
            tip = tip[:60] + "..."

        line = f"- {foods} | 진단: {diag or '없음'} | 팁: {tip or '없음'}"
        lines.append(line)

    return "\n".join(lines)

def parse_range_max(range_str: str) -> float | None:
    """
    "min~max" 형태에서 max 숫자만 추출.
    숫자가 없거나 '추정 불가'면 None.
    """
    if not range_str or "불가" in range_str:
        return None
    # 숫자 추출
    nums = re.findall(r"[\d.]+", range_str)
    if not nums:
        return None
    # 보통 "min~max"니까 마지막 숫자를 max로 간주
    try:
        return float(nums[-1])
    except Exception:
        return None
def get_rule_thresholds(profile: dict) -> dict:
    """
    MVP용 임계값 계산.
    복잡한 TDEE 대신, 체중 기반으로 끼니 단백질 최소치를 잡고
    목표에 따라 칼로리 상단 경고선을 조정.
    """
    weight = profile.get("weight")
    goal = (profile.get("goal") or "").lower()

    # 기본값 (프로필 없을 때 대비)
    if not isinstance(weight, (int, float)) or weight <= 0:
        weight = 70

    # 1) 끼니 단백질 최소치(상단 기준으로 체크)
    # 감량/유지: 체중(kg)*0.35g, 증량: *0.40g 정도를 "한 끼 상단이 이보다 낮으면 부족 가능"으로 둠
    if goal == "bulk":
        protein_min_max_threshold = max(25, int(round(weight * 0.40)))
    else:
        protein_min_max_threshold = max(25, int(round(weight * 0.35)))

    # 2) 칼로리 상단 경고선 (한 끼가 너무 큰지)
    # 감량: 낮게, 유지: 중간, 증량: 높게
    # (정교한 TDEE가 아니라 '경고선'이라 보수적으로)
    if goal == "cut":
        calorie_high_max_threshold = 750
    elif goal == "bulk":
        calorie_high_max_threshold = 950
    else:  # maintain
        calorie_high_max_threshold = 850

    # 3) 지방 상단 경고선 (한 끼)
    # 체중이 클수록 조금 허용 폭을 늘림
    fat_high_max_threshold = 35 if weight < 80 else 40

    return {
        "protein_min_max_threshold": protein_min_max_threshold,
        "calorie_high_max_threshold": calorie_high_max_threshold,
        "fat_high_max_threshold": fat_high_max_threshold,
    }

def apply_rules(result: dict, profile: dict) -> dict:
    """
    LLM 결과(result)에 룰 기반 경고/보완을 얹어 반환.
    - result["rule_flags"]: [..]
    - result["rule_note"]: "..."
    - result["diagnosis"]: 기존 진단 뒤에 필요한 경우 덧붙임
    """
    flags = []
    notes = []

    thresholds = get_rule_thresholds(profile)
    protein_thr = thresholds["protein_min_max_threshold"]
    cal_thr = thresholds["calorie_high_max_threshold"]
    fat_thr = thresholds["fat_high_max_threshold"]

    goal = (profile.get("goal") or "").lower()
    foods = " ".join(result.get("foods", [])).lower()
    macros = result.get("macros", {}) or {}

    cal_max = parse_range_max(str(macros.get("calories_kcal", "")))
    protein_max = parse_range_max(str(macros.get("protein_g", "")))
    fat_max = parse_range_max(str(macros.get("fat_g", "")))

    # 룰 1) 목표별 칼로리 상단 경고
    if cal_max is not None and cal_max >= cal_thr:
        flags.append("high_calorie_meal")
        notes.append(f"이번 끼니 칼로리 상단({int(cal_max)}kcal)이 높을 수 있어. (경고선 {cal_thr}kcal) 다음 끼니는 탄수/지방 중 하나를 줄여 균형을 맞춰보자.")

    # 룰 2) 단백질 부족 가능(상단이 기준 미만이면)
    if protein_max is not None and protein_max < protein_thr:
        flags.append("protein_low")
        notes.append(f"단백질이 부족할 가능성이 있어. (권장 상단 기준 {protein_thr}g) 다음 끼니는 단백질(살코기/계란/두부/그릭요거트)을 우선으로 잡자.")

    # 룰 3) 지방/가공식품 경고
    risky_keywords = ["튀김", "치킨", "피자", "햄버거", "라면", "떡볶이", "감자튀김", "소시지", "베이컨"]
    if (fat_max is not None and fat_max >= fat_thr) or any(k in foods for k in risky_keywords):
        flags.append("high_fat_or_processed")
        notes.append(f"지방/가공식품 비중이 높을 수 있어. (지방 상단 경고선 {fat_thr}g) 물+채소(섬유질)로 보완하고, 다음 끼니는 기름 적은 조리(구이/찜)로 가자.")

    # 룰 노트 합치기
    if notes:
        rule_note = " | ".join(notes)

        # 기존 진단에 덧붙이되 너무 길어지지 않게
        diagnosis = (result.get("diagnosis") or "").strip()
        if diagnosis:
            result["diagnosis"] = f"{diagnosis} (룰 보완: {rule_note})"
        else:
            result["diagnosis"] = f"(룰 보완: {rule_note})"

        result["rule_note"] = rule_note
    else:
        result["rule_note"] = ""

    result["rule_flags"] = flags
    return result


# -----------------------------
# 4) 이미지 -> base64 data URL 변환
# -----------------------------
def to_data_url(file_bytes: bytes, mime: str) -> str:
    b64 = base64.b64encode(file_bytes).decode("utf-8")
    return f"data:{mime};base64,{b64}"

# -----------------------------
# 5) AI 분석 함수 (사진 + 프로필 + 이전요약)
# -----------------------------

def analyze_meal(image_bytes: bytes, mime: str, profile: dict, prev_summary: str | None, meal_type: str, today_context: str | None) -> dict:

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
- 현재 끼니 타입: {meal_type}
이전 식사 요약(있으면 참고):
{prev_summary or "없음"}
오늘 맥락(있으면 참고):
{today_context or "없음"}


요청:
아래 스키마를 정확히 따르는 JSON만 출력하라. 그리고 오늘 누적 상황을 고려해서 다음 팁을 제시하라
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

# 세션 상태(이전 식사 요약)
if "prev_summary" not in st.session_state:
    st.session_state.prev_summary = make_prev_summary_from_log(n=3)

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


st.caption("현재 저장된 프로필")
with st.expander("룰 기준(프로필 기반)"):
    st.json(get_rule_thresholds(profile))
st.json(profile if profile else {"info": "아직 저장된 프로필이 없어."})
st.divider()



# -----------------------------
# 8) 사진 업로드 + AI 분석
# -----------------------------
st.header("2) 식사 사진 업로드 & 분석")

render_today_dashboard(profile) 

meal_options = ["아침", "점심", "저녁", "간식"]
default_meal = get_default_meal_type()
meal_type = st.selectbox(
    "끼니 타입",
    meal_options,
    index=meal_options.index(default_meal)
)
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

                    today = datetime.now().date().isoformat()
                    tot = daily_totals(today)
                    targets = get_daily_targets(profile)
                    today_context = f"""
                    오늘 누적(추정):
                    - 끼니 수: {tot["count"]}
                    - 누적 탄수화물: {tot["total_macros"]["carbs_g"]} g
                    - 누적 단백질: {tot["total_macros"]["protein_g"]} g (목표 {targets["protein_g"]} g)
                    - 누적 지방: {tot["total_macros"]["fat_g"]} g
                    - 누적 칼로리: {tot["total_macros"]["calories_kcal"]} kcal (목표 {targets["calories_kcal"]} kcal)
                    """
                    prev_summary = make_prev_summary_from_log(n=3)
                    result = analyze_meal(
                        image_bytes=img_bytes,
                        mime=mime,
                        profile=profile,
                        prev_summary= prev_summary,
                        meal_type=meal_type,
                        today_context=today_context
                    )
                    result = apply_rules(result, profile)
                    result["meal_type"] = meal_type

                entry = {
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "foods": result.get("foods", []),
                    "macros": result.get("macros", {}),
                    "diagnosis": result.get("diagnosis", ""),
                    "next_meal_tip": result.get("next_meal_tip", ""),
                    "rule_flags": result.get("rule_flags", []),
                    "rule_note": result.get("rule_note", ""),
                    "date": datetime.now().date().isoformat(),
                    "meal_type": meal_type,
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
                    
                """st.header("📊 오늘 누적(추정)")
                today = datetime.now().date().isoformat()
                tot = daily_totals(today)
                targets = get_daily_targets(profile) if profile else {}"""

                tm = tot["total_macros"]
                st.markdown(f"""
                - 오늘 기록된 끼니 수: **{tot["count"]}**
                - 누적 탄수화물: **{tm["carbs_g"]} g**
                - 누적 단백질: **{tm["protein_g"]} g** / 목표(대략): **{targets.get("protein_g","-")} g**
                - 누적 지방: **{tm["fat_g"]} g**
                - 누적 칼로리: **{tm["calories_kcal"]} kcal** / 목표(대략): **{targets.get("calories_kcal","-")} kcal**
                """)
      
                    
                # 다음 분석에 쓸 “이전 요약 1줄”
                #foods = ", ".join(result.get("foods", [])[:3])
                #st.session_state.prev_summary = make_prev_summary_from_log(n=3)
                #st.caption(f"다음 분석에 참고할 최근 3끼 요약:\n{st.session_state.prev_summary or '없음'}")

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
