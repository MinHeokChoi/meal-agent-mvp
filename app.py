import json
from pathlib import Path
import streamlit as st

PROFILE_PATH = Path("user_profile.json")

def load_profile():
    if PROFILE_PATH.exists():
        try:
            return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_profile(profile: dict):
    PROFILE_PATH.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")

st.set_page_config(page_title="Meal Agent MVP", layout="centered")
st.title("🍽️ Meal Agent MVP (Step 1: 프로필 저장)")

profile = load_profile()

with st.form("profile_form"):
    st.subheader("내 건강 정보 (최소)")
    height = st.number_input("키 (cm)", min_value=100, max_value=220, value=int(profile.get("height", 175)))
    weight = st.number_input("몸무게 (kg)", min_value=30, max_value=200, value=int(profile.get("weight", 70)))
    gender = st.selectbox("성별", ["male", "female", "other"], index=["male","female","other"].index(profile.get("gender","male")) if profile.get("gender","male") in ["male","female","other"] else 0)
    goal = st.selectbox("목표", ["maintain", "cut", "bulk"], index=["maintain","cut","bulk"].index(profile.get("goal","maintain")) if profile.get("goal","maintain") in ["maintain","cut","bulk"] else 0)

    submitted = st.form_submit_button("저장")

if submitted:
    new_profile = {"height": int(height), "weight": int(weight), "gender": gender, "goal": goal}
    save_profile(new_profile)
    st.success("저장 완료! user_profile.json에 기록했어.")
    profile = new_profile

st.divider()
st.caption("현재 저장된 프로필")
st.json(profile if profile else {"info": "아직 저장된 프로필이 없어."})
