"""미국 경기 국면 판단 대시보드 (Streamlit).

실행: streamlit run app.py
배포: share.streamlit.io 에서 이 레포 연결.
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.fetch import load, upsert_manual_pmi, MANUAL_PMI
from src.composite import build_composites, momentum
from src.classify import classify, confidence, phase_duration, PHASE_EN
from src.indicators import INDICATORS, GROUP_KO, by_key
from src.rotation import ROTATION, PHASE_COLORS

st.set_page_config(page_title="경기 국면 판단", page_icon="📊", layout="wide")


# ─────────────────────────────────────────────────────────────
# 비밀번호 게이트 (Streamlit Secrets에 [auth] password 설정 시에만 작동)
# ─────────────────────────────────────────────────────────────
def password_ok():
    try:
        pw = st.secrets["auth"]["password"]
    except Exception:
        return True  # secrets 없으면(로컬) 통과
    if st.session_state.get("authed"):
        return True
    with st.form("login"):
        v = st.text_input("비밀번호", type="password")
        if st.form_submit_button("로그인"):
            if v == pw:
                st.session_state["authed"] = True
                st.rerun()
            st.error("비밀번호가 틀렸습니다.")
    return False


if not password_ok():
    st.stop()


# ─────────────────────────────────────────────────────────────
# 데이터 로드 & 계산
# ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=60 * 60 * 12)
def get_data():
    return load()


if st.sidebar.button("🔄 데이터 새로고침"):
    get_data.clear()

df = get_data()
composites, comps = build_composites(df)
result = classify(composites)
valid = result.dropna(subset=["phase"])
latest = valid.iloc[-1]
phase = latest["phase"]
conf = confidence(latest)
dur = phase_duration(result)
asof = valid.index[-1].strftime("%Y-%m")
color = PHASE_COLORS[phase]


# ─────────────────────────────────────────────────────────────
# 헤더: 현재 국면
# ─────────────────────────────────────────────────────────────
st.markdown(f"## 📊 미국 경기 국면 판단 &nbsp;·&nbsp; 기준월 {asof}")

c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
c1.markdown(
    f"<div style='background:{color};color:#fff;padding:16px;border-radius:12px;text-align:center'>"
    f"<div style='font-size:13px;opacity:.85'>현재 국면 · {PHASE_EN[phase]} · {dur}개월째</div>"
    f"<div style='font-size:38px;font-weight:800;line-height:1.1'>{phase}</div>"
    f"<div style='font-size:13px;opacity:.9'>{ROTATION[phase]['risk']}</div></div>",
    unsafe_allow_html=True,
)


def _dir(v):
    return "▲ 상승" if v > 0 else "▼ 하락"


c2.metric("판정 신뢰도", f"{conf}%")
c3.metric("선행지표 방향", _dir(latest["lead_mom"]), f"{latest['lead_mom']:+.2f}")
c4.metric("후행지표 방향", _dir(latest["lag_mom"]), f"{latest['lag_mom']:+.2f}")

# 원시 사분면이 확정 국면과 다르면 = 전환 후보 관찰 중
if pd.notna(latest.get("raw_phase")) and latest["raw_phase"] != phase:
    st.info(f"👀 최근 지표는 **{latest['raw_phase']}** 방향입니다 — 3개월 연속 지속되면 국면이 전환됩니다.")
elif conf < 25:
    st.warning("⚠️ 신뢰도가 낮습니다 — 국면 경계(모멘텀 0 부근)일 가능성이 큽니다.")


# ─────────────────────────────────────────────────────────────
# 경기 시계(2×2) + 합성지수 시계열
# ─────────────────────────────────────────────────────────────
def phase_clock(res, n=12):
    d = res.dropna(subset=["lead_mom", "lag_mom"]).tail(n)
    m = max(d["lead_mom"].abs().max(), d["lag_mom"].abs().max(), 0.3) * 1.25
    fig = go.Figure()
    for name, x, y in [("성장", m / 2, m / 2), ("회복", m / 2, -m / 2),
                       ("둔화", -m / 2, m / 2), ("침체", -m / 2, -m / 2)]:
        fig.add_annotation(x=x, y=y, text=name, showarrow=False, opacity=0.45,
                           font=dict(size=20, color=PHASE_COLORS[name]))
    fig.add_hline(y=0, line_color="#bbb")
    fig.add_vline(x=0, line_color="#bbb")
    fig.add_trace(go.Scatter(x=d["lead_mom"], y=d["lag_mom"], mode="lines+markers",
                             line=dict(color="#ccc"), marker=dict(size=6),
                             text=[t.strftime("%Y-%m") for t in d.index], name="궤적"))
    last = d.iloc[-1]
    fig.add_trace(go.Scatter(x=[last["lead_mom"]], y=[last["lag_mom"]], mode="markers",
                             marker=dict(size=20, color=PHASE_COLORS[last["phase"]],
                                         line=dict(width=2, color="#fff")), name="현재"))
    fig.update_layout(height=430, showlegend=False, margin=dict(l=10, r=10, t=30, b=10),
                      xaxis_title="← 선행 모멘텀(둔화/침체)   ·   선행 모멘텀(회복/성장) →",
                      yaxis_title="← 후행(회복/침체)   ·   후행(성장/둔화) →",
                      xaxis_range=[-m, m], yaxis_range=[-m, m])
    return fig


def composite_chart(comp, df, years=12):
    start = comp.index.max() - pd.DateOffset(years=years)
    c = comp[comp.index >= start]
    fig = go.Figure()
    # NBER 침체 음영
    if "nber_rec" in df.columns:
        rec = df.loc[df.index >= start, "nber_rec"].fillna(0)
        inrec = rec > 0
        runs, s = [], None
        for t, v in inrec.items():
            if v and s is None:
                s = t
            elif not v and s is not None:
                runs.append((s, t)); s = None
        if s is not None:
            runs.append((s, inrec.index[-1]))
        for a, b in runs:
            fig.add_vrect(x0=a, x1=b, fillcolor="gray", opacity=0.15, line_width=0)
    for k, nm, col in [("leading", "선행", "#2E86DE"),
                       ("coincident", "동행", "#27AE60"),
                       ("lagging", "후행", "#E67E22")]:
        if k in c:
            fig.add_trace(go.Scatter(x=c.index, y=c[k], name=nm, mode="lines",
                                     line=dict(color=col)))
    fig.add_hline(y=0, line_color="#bbb", line_dash="dot")
    fig.update_layout(height=430, margin=dict(l=10, r=10, t=30, b=10), yaxis_title="z-score",
                      legend=dict(orientation="h", y=1.08))
    return fig


def phase_timeline(res, years=12):
    """확정 국면 히스토리를 색 띠로 표시."""
    ph = res["phase"].dropna()
    start = ph.index.max() - pd.DateOffset(years=years)
    ph = ph[ph.index >= start]
    rows = []
    for _, seg in ph.groupby((ph != ph.shift()).cumsum()):
        rows.append({
            "국면": seg.iloc[0],
            "시작": seg.index[0] - pd.DateOffset(months=1),  # 월말 인덱스 → 해당 월 폭 확보
            "끝": seg.index[-1],
            "기간": f"{seg.index[0].strftime('%Y-%m')} ~ {seg.index[-1].strftime('%Y-%m')} ({len(seg)}개월)",
            "y": "",
        })
    fig = px.timeline(pd.DataFrame(rows), x_start="시작", x_end="끝", y="y",
                      color="국면", color_discrete_map=PHASE_COLORS,
                      hover_data={"기간": True, "시작": False, "끝": False, "y": False},
                      category_orders={"국면": ["회복", "성장", "둔화", "침체"]})
    fig.update_layout(height=110, margin=dict(l=10, r=10, t=5, b=5),
                      yaxis=dict(visible=False), xaxis_title=None,
                      legend=dict(orientation="h", title=None, y=1.6))
    return fig


left, right = st.columns(2)
left.subheader("🧭 경기 시계 (최근 24개월)")
left.plotly_chart(phase_clock(result, n=24), width="stretch")
right.subheader("📈 합성지수 추이 (회색=NBER 침체)")
right.plotly_chart(composite_chart(composites, df), width="stretch")

st.subheader("🗓️ 국면 히스토리 (최근 12년)")
st.plotly_chart(phase_timeline(result), width="stretch")
st.caption(
    "이상적 순환은 회복→성장→둔화→침체 순이지만, 실제로는 역행도 나타납니다 — "
    "둔화→성장(재가속·연착륙), 회복→침체(가짜 회복), 성장→침체(급락, 예: 코로나). "
    "1999~2026년 전환 31회 중 정방향 19회 · 역행/건너뜀 12회."
)


# ─────────────────────────────────────────────────────────────
# 로테이션 추천
# ─────────────────────────────────────────────────────────────
st.subheader(f"🔄 {phase} 국면 로테이션 추천")
r = ROTATION[phase]
rc1, rc2 = st.columns(2)
rc1.markdown("**국가 · 지수 · 스타일**")
rc1.markdown("\n".join(f"- {x}" for x in r["country_index"]))
rc2.markdown("**선호 섹터**")
rc2.markdown("\n".join(f"- {x}" for x in r["sectors"]))


# ─────────────────────────────────────────────────────────────
# 지표별 상세
# ─────────────────────────────────────────────────────────────
with st.expander("📋 지표별 상세 (표준화값 · 방향)"):
    rows = []
    for ind in INDICATORS:
        if ind.key not in comps.columns:
            continue
        z = comps[ind.key].dropna()
        if z.empty:
            continue
        mom = momentum(comps[ind.key]).iloc[-1]
        arrow = "▲ 상승" if mom > 0 else ("▼ 하락" if mom < 0 else "— 보합")
        rows.append({"그룹": GROUP_KO[ind.group], "지표": ind.name_ko,
                     "표준화값(z)": round(float(z.iloc[-1]), 2), "방향": arrow,
                     "비고": ind.note})
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

# ─────────────────────────────────────────────────────────────
# 실제 PMI 수동 입력 (웹에서 바로)
# ─────────────────────────────────────────────────────────────
def push_pmi_to_github(csv_text):
    """secrets에 [github] token/repo 있으면 커밋(영구 저장). 없으면 None."""
    try:
        gh = st.secrets["github"]
        token, repo = gh["token"], gh["repo"]
    except Exception:
        return None
    import base64
    import requests
    api = f"https://api.github.com/repos/{repo}/contents/data/pmi_manual.csv"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    r = requests.get(api, headers=headers, timeout=15)
    payload = {
        "message": "data: PMI 수동 입력 (웹)",
        "content": base64.b64encode(csv_text.encode()).decode(),
    }
    if r.status_code == 200:
        payload["sha"] = r.json()["sha"]
    requests.put(api, headers=headers, json=payload, timeout=15).raise_for_status()
    return True


with st.expander("📝 실제 PMI 수동 입력 (ISM 발표 후, 선택)"):
    if msg := st.session_state.pop("pmi_saved", None):
        st.success(msg)
    st.caption(
        "매월 1영업일 ISM(또는 S&P Global) 발표 후 헤드라인 PMI를 입력하세요. "
        "입력 즉시 화면에 반영되고, 12개월 이상 쌓이면 선행지표 합성에도 포함됩니다."
    )
    months = [(pd.Timestamp.today().replace(day=1) - pd.DateOffset(months=i)).strftime("%Y-%m")
              for i in range(1, 19)]
    with st.form("pmi_form"):
        fc1, fc2, fc3 = st.columns([1, 1, 1])
        in_month = fc1.selectbox("대상 월", months)
        in_val = fc2.number_input("PMI 값", min_value=20.0, max_value=80.0, value=50.0, step=0.1)
        fc3.markdown("<br>", unsafe_allow_html=True)
        if fc3.form_submit_button("💾 저장"):
            csv_text = upsert_manual_pmi(in_month, in_val)   # 로컬 즉시 반영
            pushed = None
            try:
                pushed = push_pmi_to_github(csv_text)        # 토큰 있으면 영구 저장
            except Exception as e:
                st.error(f"GitHub 저장 실패(로컬엔 반영됨): {e}")
            st.session_state["pmi_saved"] = (
                f"{in_month} = {in_val} 저장 완료"
                + (" · GitHub 커밋됨(영구 저장)" if pushed
                   else " · ⚠️ 이 값은 재배포 시 사라집니다 — 영구 저장은 secrets에 [github] token 설정")
            )
            get_data.clear()
            st.rerun()
    try:
        entries = pd.read_csv(MANUAL_PMI).dropna()
        if not entries.empty:
            st.dataframe(entries.tail(12), width="stretch", hide_index=True)
    except Exception:
        pass

st.caption(
    f"데이터 최신월: {df.index[-1].strftime('%Y-%m')} · "
    "출처: FRED, Yahoo Finance · 제조업 선행신호는 지역 연준 서베이(필라델피아·엠파이어스테이트). "
    "실제 ISM/S&P PMI는 위 입력폼 또는 GitHub의 data/pmi_manual.csv 편집으로 추가할 수 있습니다."
)
