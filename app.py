import json
from pathlib import Path
from datetime import datetime
import streamlit as st

# -----------------------------
# 1) 파일 경로(저장 위치) 설정
# -----------------------------
PROFILE_PATH = Path("user_profile.json")
MEALS_DIR = Path("meals")
LOG_PATH = Path("meals_log.json")

# -----------------------------
# 2) 프로필(건강정보) 불러오기/저장하기 함수
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
# 3) 식사 기록 로그(메타데이터) 불러오기/추가하기 함수
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
        encoding="utf-8")

# -----------------------------
# 4) Streamlit 페이지 설정
# -----------------------------
st.set_page_config(page_title="Meal Agent MVP", layout="centered")
st.title("🍽️ Meal Agent MVP (Step 2: 사진 업로드)")

# -----------------------------
# 5) 프로필 섹션
# -----------------------------
st.header("1) 내 건강 정보 저장")
profile = load_profile()

with st.form("profile_form"):
    st.subheader("프로필 입력 (최소)")
    height = st.number_input(
        "키 (cm)",
        min_value=100, max_value=220,
        value=int(profile.get("height", 175))
    )
    weight = st.number_input(
        "몸무게 (kg)",
        min_value=30, max_value=200,
        value=int(profile.get("weight", 70))
    )
    gender = st.selectbox(
        "성별",
        ["male", "female", "other"],
        index=["male", "female", "other"].index(profile.get("gender", "male"))
        if profile.get("gender", "male") in ["male", "female", "other"] else 0
    )
    goal = st.selectbox(
        "목표",
        ["maintain", "cut", "bulk"],
        index=["maintain", "cut", "bulk"].index(profile.get("goal", "maintain"))
        if profile.get("goal", "maintain") in ["maintain", "cut", "bulk"] else 0
    )

    submitted = st.form_submit_button("저장")

if submitted:
    new_profile = {
        "height": int(height),
        "weight": int(weight),
        "gender": gender,
        "goal": goal
    }
    save_profile(new_profile)
    st.success("저장 완료! user_profile.json에 기록했어.")
    profile = new_profile

st.caption("현재 저장된 프로필")
st.json(profile if profile else {"info": "아직 저장된 프로필이 없어."})

st.divider()

# -----------------------------
# 6) 식사 사진 업로드 섹션
# -----------------------------
st.header("2) 식사 사진 업로드")

uploaded = st.file_uploader(
    "식사 사진을 올려줘 (jpg/png)",
    type=["jpg", "jpeg", "png"]
)

if uploaded is None:
    st.info("사진을 올리면 여기에서 바로 보여줄게.")
else:
    # 6-1) 업로드된 사진 화면에 보여주기
    st.image(uploaded, caption="업로드한 식사 사진", use_container_width=True)

    # 6-2) 저장 버튼(선택): 파일로 저장 + 로그 남기기
    if st.button("이 사진 저장하기 (로그에 기록)"):
        MEALS_DIR.mkdir(exist_ok=True)

        now = datetime.now()
        ts = now.strftime("%Y%m%d_%H%M%S")  # 예: 20251229_071530

        # 업로드 파일 이름에서 확장자만 가져오기
        original_name = uploaded.name
        ext = original_name.split(".")[-1].lower()  # jpg/png 등

        # 저장할 파일 경로 만들기
        save_path = MEALS_DIR / f"meal_{ts}.{ext}"

        # 실제 파일 저장 (바이트 그대로)
        save_path.write_bytes(uploaded.getvalue())

        # 로그에 기록 (나중에 AI 분석 붙일 때 사용)
        entry = {
            "timestamp": now.isoformat(timespec="seconds"),
            "image_path": str(save_path),
            "note": "Step2: 사진만 저장(아직 AI 분석 없음)"
        }
        append_log(entry)

        st.success(f"저장 완료: {save_path}")

st.divider()

# -----------------------------
# 7) 최근 로그 보기(선택)
# -----------------------------
st.header("3) 최근 기록 보기")
log = load_log()
if not log:
    st.write("아직 저장된 기록이 없어.")
else:
    # 마지막 5개만 보여주기
    for item in log[-5:][::-1]:
        st.write(f"- {item['timestamp']} / {item['image_path']} / {item.get('note','')}")
