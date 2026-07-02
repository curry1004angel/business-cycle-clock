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

PHASE_KO = ["회복", "성장", "둔화", "침체"]
PHASE_EN = {"회복": "Recovery", "성장": "Growth", "둔화": "Slowdown", "침체": "Recession"}

DEADBAND = 0.10  # 모멘텀 중립대: 이보다 작으면 방향 전환으로 안 봄
HOLD_MAX = 6     # 중립대에서 직전 방향을 유지하는 최대 개월 수(만료)
CONFIRM = 3      # 국면 전환 확정에 필요한 연속 개월 수


def _phase(lead_dir, lag_dir):
    if lead_dir > 0 and lag_dir <= 0:
        return "회복"
    if lead_dir > 0 and lag_dir > 0:
        return "성장"
    if lead_dir <= 0 and lag_dir > 0:
        return "둔화"
    return "침체"


def _sign_hold(m, deadband=DEADBAND, hold_max=HOLD_MAX):
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


def classify(composites):
    """월별 국면 라벨 + 합성/모멘텀을 담은 DataFrame 반환.

    phase     : 확정 국면(중립대+확정규칙 적용) — 화면 표시용
    raw_phase : 매월 원시 사분면 — 참고용
    """
    lead = composites.get("leading")
    coin = composites.get("coincident")
    lag = composites.get("lagging")
    lead_m, coin_m, lag_m = momentum(lead), momentum(coin), momentum(lag)

    lead_s, lag_s = _sign_hold(lead_m), _sign_hold(lag_m)
    raw = pd.Series(
        [np.nan if (pd.isna(a) or pd.isna(b)) else _phase(a, b)
         for a, b in zip(lead_s, lag_s)],
        index=composites.index, dtype="object",
    )
    phase = _hysteresis(raw)

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
