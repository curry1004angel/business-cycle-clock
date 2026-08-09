"""4국면 판정 엔진.

핵심 규칙(주어진 표에서 도출): 선행 × 후행 방향의 2×2 사분면으로 국면이 결정된다.

  선행↑ & 후행↓ → 회복   (선행 반등, 후행 아직 하락)
  선행↑ & 후행↑ → 성장   (모두 상승)
  선행↓ & 후행↑ → 둔화   (선행 꺾임, 후행 관성 상승)
  선행↓ & 후행↓ → 침체   (모두 하락)

동행지표(바닥→상승→전환→하락)는 판정 확신도(confidence) 보정에 쓴다.

노이즈 억제 장치 (1999~2026 백테스트로 파라미터 선정):
  1) 중립대(DEADBAND): 모멘텀 |z|<0.10 이면 방향을 바꾸지 않고 직전 방향 유지
  2) 중립대 만료(HOLD_MAX): 단, 6개월 넘게 중립대에 머물면 직전 방향이 낡은
     정보가 되므로 현재 부호를 따름 — 2025년 후행 모멘텀이 1년 내내 중립대에
     있으면서 옛 '하락'을 끌고 와 연착륙(둔화)을 침체로 오판했던 결함의 수정
  3) 확정규칙(CONFIRM): 새 국면이 3개월 연속 관측되어야 공식 국면 전환
→ 27년간 전환 105회(평균 3.2개월) → 32회(평균 10.2개월)로 안정화,
  NBER 침체월의 93%를 침체로 포착 (닷컴 00.11, 금융위기 08.03, 2022긴축 22.09 진입).
"""

import numpy as np
import pandas as pd

from .composite import momentum
from .indicators import INDICATORS
from .rotation import ROTATION

PHASE_KO = ["회복", "성장", "둔화", "침체"]
PHASE_EN = {"회복": "Recovery", "성장": "Growth", "둔화": "Slowdown", "침체": "Recession"}

DEADBAND = 0.10  # 모멘텀 중립대: 이보다 작으면 방향 전환으로 안 봄
HOLD_MAX = 6     # 중립대에서 직전 방향을 유지하는 최대 개월 수(만료)
CONFIRM = 3      # 국면 전환 확정에 필요한 연속 개월 수

# ─────────────────────────────────────────────────────────────
# 감도 프리셋 — 모멘텀을 얼마나 평활할지 선택
#
# 창을 줄이면 모멘텀 크기가 작아져 중립대에 갇히고 확정 카운터가 리셋되므로,
# 창마다 중립대·확정개월을 따로 최적화했다(1975~2026 격자 탐색).
# stats는 그 백테스트 실측값 — 화면에 그대로 노출해 선택 근거로 쓴다.
# ─────────────────────────────────────────────────────────────
PRESETS = {
    "안정형 (6개월 평활)": dict(smooth=6, window=6, deadband=0.10, confirm=3,
                          stats="전환 67회 · 평균 9.0개월 · NBER 포착 84% · 오경보 15%"),
    "민감형 (3개월)": dict(smooth=3, window=3, deadband=0.10, confirm=5,
                       stats="전환 44회 · 평균 13.7개월 · NBER 포착 97% · 오경보 21%"),
    "전월 대비 (1개월)": dict(smooth=1, window=1, deadband=0.10, confirm=4,
                         stats="전환 43회 · 평균 14.0개월 · NBER 포착 62% · 오경보 17%"),
}
DEFAULT_PRESET = "안정형 (6개월 평활)"


def preset(name=None):
    """프리셋 파라미터. 이름이 없거나 모르면 기본값."""
    return PRESETS.get(name or DEFAULT_PRESET, PRESETS[DEFAULT_PRESET])


def _phase(lead_dir, lag_dir):
    if lead_dir > 0 and lag_dir <= 0:
        return "회복"
    if lead_dir > 0 and lag_dir > 0:
        return "성장"
    if lead_dir <= 0 and lag_dir > 0:
        return "둔화"
    return "침체"


def _sign_hold(m, deadband=DEADBAND, hold_max=HOLD_MAX):  # noqa: D401
    """중립대 안(|m|<deadband)에서는 직전 방향 유지 — 단 hold_max개월까지만.

    그 이상 머물면 직전 방향은 낡은 정보이므로 현재 부호(약해도)를 따른다.
    """
    out, prev, held = [], 1.0, 0
    for v in m:
        if pd.isna(v):
            out.append(np.nan)
            continue
        if abs(v) >= deadband:
            prev = 1.0 if v > 0 else -1.0
            held = 0
        else:
            held += 1
            if held > hold_max:
                prev = 1.0 if v > 0 else -1.0
        out.append(prev)
    return pd.Series(out, index=m.index)


def _hysteresis(raw, confirm=CONFIRM):
    """새 국면이 confirm개월 연속일 때만 공식 국면을 전환."""
    phase, cur, cand, cnt = [], None, None, 0
    for p in raw:
        if isinstance(p, float) and pd.isna(p):
            phase.append(np.nan)
            continue
        if cur is None:
            cur = p
        elif p != cur:
            if p == cand:
                cnt += 1
            else:
                cand, cnt = p, 1
            if cnt >= confirm:
                cur, cand, cnt = p, None, 0
        else:
            cand, cnt = None, 0
        phase.append(cur)
    return pd.Series(phase, index=raw.index)


def classify(composites, p=None):
    """월별 국면 라벨 + 합성/모멘텀을 담은 DataFrame 반환.

    phase     : 확정 국면(중립대+확정규칙 적용) — 화면 표시용
    raw_phase : 매월 원시 사분면 — 참고용
    p         : 감도 프리셋(preset()) — 없으면 기본값
    """
    p = p or preset()
    lead = composites.get("leading")
    coin = composites.get("coincident")
    lag = composites.get("lagging")
    sm, w = p["smooth"], p["window"]
    lead_m = momentum(lead, sm, w)
    coin_m = momentum(coin, sm, w)
    lag_m = momentum(lag, sm, w)

    lead_s = _sign_hold(lead_m, p["deadband"])
    lag_s = _sign_hold(lag_m, p["deadband"])
    raw = pd.Series(
        [np.nan if (pd.isna(a) or pd.isna(b)) else _phase(a, b)
         for a, b in zip(lead_s, lag_s)],
        index=composites.index, dtype="object",
    )
    phase = _hysteresis(raw, p["confirm"])

    return pd.DataFrame({
        "phase": phase, "raw_phase": raw,
        "leading": lead, "coincident": coin, "lagging": lag,
        "lead_mom": lead_m, "coin_mom": coin_m, "lag_mom": lag_m,
    })


def phase_duration(result):
    """현재 확정 국면이 몇 개월째 지속 중인지."""
    ph = result["phase"].dropna()
    if ph.empty:
        return 0
    cur = ph.iloc[-1]
    n = 0
    for p in reversed(ph.tolist()):
        if p != cur:
            break
        n += 1
    return n


# ─────────────────────────────────────────────────────────────
# 5종 방향 라벨 + 패턴 일치도 (NH 스타일 보조 판정)
# ─────────────────────────────────────────────────────────────
# 문자열 비교로는 '반등'과 '상승'이 0점이 되어 일치도가 항상 바닥에 깔린다.
# 방향을 수치화해 거리로 부분점수를 주기 위한 척도.
DIRECTION_VALUE = {"상승": 1.0, "반등": 0.5, "바닥": 0.0, "전환": -0.5, "하락": -1.0}
DIRECTION_ARROW = {"상승": "↑", "반등": "↗", "바닥": "→", "전환": "↷", "하락": "↓"}
TURN_LAG = 3  # 방향 전환 판정에 쓰는 비교 시차(개월)


def direction5(series, band=None, turn_lag=TURN_LAG, p=None):
    """5종 방향 라벨(상승/반등/바닥/전환/하락).

    반등·전환은 모멘텀 부호가 turn_lag개월 전 대비 뒤집혔는지(2차 정보)로,
    바닥은 모멘텀이 중립대 안이면서 수준이 평균 이하인지로 판정한다.
    p = 감도 프리셋(preset()) — 없으면 기본값.
    """
    p = p or preset()
    band = p["deadband"] if band is None else band
    if series is None or series.dropna().empty:
        return None
    m = momentum(series, p["smooth"], p["window"]).dropna()
    if m.empty:
        return None
    cur = float(m.iloc[-1])
    prev = float(m.iloc[-1 - turn_lag]) if len(m) > turn_lag else np.nan
    lvl = series.dropna()
    level = float(lvl.iloc[-1]) if not lvl.empty else np.nan

    if pd.notna(prev):
        if cur > 0 and prev <= 0:
            return "반등"
        if cur < 0 and prev >= 0:
            return "전환"
    if abs(cur) <= band and (pd.isna(level) or level <= 0):
        return "바닥"
    return "상승" if cur > 0 else "하락"


def _score(actual, expected):
    """방향 두 개의 일치도 0~1 (최대 거리 2.0 = 상승 vs 하락)."""
    return 1.0 - abs(DIRECTION_VALUE[actual] - DIRECTION_VALUE[expected]) / 2.0


def pattern_match(composites, comps, p=None):
    """국면별 패턴 일치도(%) + 방향 라벨.

    반환: (scores, group_dirs, ind_dirs)
      scores     : {국면: 일치도%}  — 지표 14개 단위 채점(그룹 3개보다 동점 적음)
      group_dirs : {선행/동행/후행: 방향}  — 화면 상단 요약용
      ind_dirs   : [(그룹, 지표명, 방향)]  — 지표별 상세용
    """
    p = p or preset()
    # ROTATION["회복"]["indicator"] 의 키에 맞춘 짧은 그룹명
    SHORT = {"leading": "선행", "coincident": "동행", "lagging": "후행"}

    group_dirs, ind_dirs = {}, []
    for g, ko in SHORT.items():
        if g in composites:
            d = direction5(composites[g], p=p)
            if d:
                group_dirs[ko] = d
    for ind in INDICATORS:
        if ind.key in comps.columns:
            d = direction5(comps[ind.key], p=p)
            if d:
                ind_dirs.append((SHORT[ind.group], ind.name_ko, d))

    scores = {}
    for phase, spec in ROTATION.items():
        exp = spec["indicator"]  # {"선행": "반등", "동행": "바닥", "후행": "하락"}
        vals = [_score(d, exp[grp]) for grp, _name, d in ind_dirs if grp in exp]
        scores[phase] = round(100 * sum(vals) / len(vals), 1) if vals else 0.0
    return scores, group_dirs, ind_dirs


def _pct_rank(history, value):
    """|value|가 |history| 분포에서 상위 몇 %인지 (0~100)."""
    h = history.abs().dropna()
    if h.empty or pd.isna(value):
        return 50.0
    return float((h <= abs(value)).mean() * 100)


def confidence_detail(result, t=None):
    """판정 신뢰도(0~100)와 구성 요소.

    구성 (가중합):
      선행 모멘텀 강도 40% — 현재 |선행 모멘텀|의 1999~ 역사적 백분위
      후행 모멘텀 강도 30% — 현재 |후행 모멘텀|의 역사적 백분위
      동행지표 일치   30% — 동행 방향이 국면 기대와 일치하면 50+강도/2,
                             역행하면 50-강도/2 (중립 50)

    해석: ~50 = 역사적 평균 수준의 신호, 70↑ = 국면 한복판의 강한 신호,
    30↓ = 모멘텀이 약한 경계 구간(전환 가능성).
    """
    valid = result.dropna(subset=["phase"])
    row = valid.loc[t] if t is not None else valid.iloc[-1]

    lead_pct = _pct_rank(valid["lead_mom"], row["lead_mom"])
    lag_pct = _pct_rank(valid["lag_mom"], row["lag_mom"])

    expected_up = row["phase"] in ("회복", "성장")  # 회복·성장이면 동행 상승이 정상
    if pd.isna(row["coin_mom"]):
        coin_score = 50.0
    else:
        coin_pct = _pct_rank(valid["coin_mom"], row["coin_mom"])
        agree = (row["coin_mom"] > 0) == expected_up
        coin_score = 50 + coin_pct / 2 if agree else 50 - coin_pct / 2

    total = 0.4 * lead_pct + 0.3 * lag_pct + 0.3 * coin_score
    return {
        "total": int(round(total)),
        "lead": int(round(lead_pct)),
        "lag": int(round(lag_pct)),
        "coin": int(round(coin_score)),
    }


def confidence(row):
    """(구버전 호환) 단일 행 기반 근사 — 새 코드는 confidence_detail 사용."""
    ls = np.tanh(abs(row["lead_mom"])) if pd.notna(row["lead_mom"]) else 0.0
    gs = np.tanh(abs(row["lag_mom"])) if pd.notna(row["lag_mom"]) else 0.0
    base = (ls + gs) / 2
    expected_up = row["phase"] in ("회복", "성장")
    if pd.notna(row["coin_mom"]):
        agree = 1.0 if (row["coin_mom"] > 0) == expected_up else 0.6
    else:
        agree = 0.8
    return int(round(base * agree * 100))
