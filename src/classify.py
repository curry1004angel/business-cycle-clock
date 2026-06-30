"""4국면 판정 엔진.

핵심 규칙(주어진 표에서 도출): 선행 × 후행 방향의 2×2 사분면으로 국면이 결정된다.

  선행↑ & 후행↓ → 회복   (선행 반등, 후행 아직 하락)
  선행↑ & 후행↑ → 성장   (모두 상승)
  선행↓ & 후행↑ → 둔화   (선행 꺾임, 후행 관성 상승)
  선행↓ & 후행↓ → 침체   (모두 하락)

동행지표(바닥→상승→전환→하락)는 판정 확신도(confidence) 보정에 쓴다.
"""

import numpy as np
import pandas as pd

from .composite import momentum

PHASE_KO = ["회복", "성장", "둔화", "침체"]
PHASE_EN = {"회복": "Recovery", "성장": "Growth", "둔화": "Slowdown", "침체": "Recession"}


def _phase(lead_dir, lag_dir):
    if lead_dir > 0 and lag_dir <= 0:
        return "회복"
    if lead_dir > 0 and lag_dir > 0:
        return "성장"
    if lead_dir <= 0 and lag_dir > 0:
        return "둔화"
    return "침체"


def classify(composites):
    """월별 국면 라벨 + 합성/모멘텀을 담은 DataFrame 반환."""
    lead = composites.get("leading")
    coin = composites.get("coincident")
    lag = composites.get("lagging")
    lead_m, coin_m, lag_m = momentum(lead), momentum(coin), momentum(lag)

    phase = pd.Series(index=composites.index, dtype="object")
    for t in composites.index:
        ld = lead_m.get(t, np.nan)
        lg = lag_m.get(t, np.nan)
        phase[t] = np.nan if (pd.isna(ld) or pd.isna(lg)) else _phase(ld, lg)

    return pd.DataFrame({
        "phase": phase,
        "leading": lead, "coincident": coin, "lagging": lag,
        "lead_mom": lead_m, "coin_mom": coin_m, "lag_mom": lag_m,
    })


def confidence(row):
    """0~100. 모멘텀 강도 + 동행지표의 방향 일치도로 보정."""
    ls = np.tanh(abs(row["lead_mom"])) if pd.notna(row["lead_mom"]) else 0.0
    gs = np.tanh(abs(row["lag_mom"])) if pd.notna(row["lag_mom"]) else 0.0
    base = (ls + gs) / 2

    expected_up = row["phase"] in ("회복", "성장")  # 회복·성장이면 동행 상승이 정상
    if pd.notna(row["coin_mom"]):
        agree = 1.0 if (row["coin_mom"] > 0) == expected_up else 0.6
    else:
        agree = 0.8
    return int(round(base * agree * 100))
