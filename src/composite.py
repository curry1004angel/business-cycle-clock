"""합성지수 계산.

각 지표를 변환(YoY 또는 원값) → 표준화(z-score) → 그룹 평균으로
선행/동행/후행 합성지수를 만든다. 모멘텀(방향)은 평활 후 변화량으로 계산.
"""

import numpy as np
import pandas as pd

from .indicators import INDICATORS, groups


def _transform(s, how, invert=False):
    s = s.astype(float)
    out = s.pct_change(12) * 100 if how == "yoy" else s
    return -out if invert else out


def _zscore(s):
    sd = s.std(ddof=0)
    if not sd or np.isnan(sd):
        return s * 0.0
    return (s - s.mean()) / sd


MIN_OBS = 12  # 표본이 이보다 적으면 z-score가 왜곡되므로 합성에서 제외


def build_components(df):
    """지표별 변환·표준화된 z-score DataFrame."""
    cols = {}
    for ind in INDICATORS:
        if ind.key in df.columns and df[ind.key].notna().sum() >= MIN_OBS:
            cols[ind.key] = _zscore(_transform(df[ind.key], ind.transform, ind.invert))
    return pd.DataFrame(cols, index=df.index)


def build_composites(df):
    """(composites, components) 반환. composites = 선행/동행/후행 합성 z-score."""
    comps = build_components(df)
    out = pd.DataFrame(index=df.index)
    for gname, keys in groups().items():
        use = [k for k in keys if k in comps.columns]
        if use:
            out[gname] = comps[use].mean(axis=1)
    return out, comps


def momentum(s, smooth=6, window=6):
    """노이즈를 줄인 방향 신호: smooth개월 평활 후 window개월 변화량.

    기본값 6/6은 1999~2026 백테스트로 선정 — 3/3은 27년간 국면 전환이
    105회(평균 3.2개월)로 비현실적이었고, 6/6 + 중립대·확정규칙 적용 시
    31회(평균 10.5개월)로 실제 경기 사이클 길이에 부합하며
    NBER 침체월의 89%를 침체로 포착했다.
    """
    if s is None:
        return pd.Series(dtype=float)
    sm = s.rolling(smooth, min_periods=1).mean()
    return sm.diff(window)
