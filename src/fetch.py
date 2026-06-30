"""데이터 수집 레이어.

FRED(키 불필요, pandas-datareader) + yfinance(주가) + 수동 CSV(선택)를
월말(ME) 기준 단일 DataFrame으로 합친다.

- fetch_all() : 라이브 수집 (GitHub Actions / 로컬에서 사용)
- load()      : data/series.parquet 캐시가 있으면 읽고, 없으면 라이브 수집
"""

import os
import warnings

import pandas as pd

from .indicators import INDICATORS, AUX

warnings.filterwarnings("ignore")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
PARQUET = os.path.join(DATA_DIR, "series.parquet")
MANUAL_PMI = os.path.join(DATA_DIR, "pmi_manual.csv")


def _fred(code, start):
    from pandas_datareader import data as pdr
    return pdr.DataReader(code, "fred", start)[code]


def _yahoo(code, start):
    import yfinance as yf
    df = yf.download(code, start=start, interval="1mo", progress=False, auto_adjust=True)
    close = df["Close"]
    if isinstance(close, pd.DataFrame):  # 멀티인덱스 컬럼 방어
        close = close.iloc[:, 0]
    return close


def _manual_pmi():
    if not os.path.exists(MANUAL_PMI):
        raise FileNotFoundError(MANUAL_PMI)
    m = pd.read_csv(MANUAL_PMI).dropna()
    if m.empty:
        raise ValueError("manual PMI 비어 있음")
    m["date"] = pd.to_datetime(m["date"])
    return m.set_index("date").iloc[:, 0]


def fetch_all(start="1998-01-01"):
    """모든 지표를 받아 월말 기준 단일 DataFrame으로 반환."""
    frames = {}
    for ind in (INDICATORS + AUX):
        try:
            if ind.source == "fred":
                s = _fred(ind.code, start)
            elif ind.source == "yahoo":
                s = _yahoo(ind.code, start)
            elif ind.source == "manual":
                s = _manual_pmi()
            else:
                continue
            s.index = pd.to_datetime(s.index)
            frames[ind.key] = s.resample("ME").mean()
        except Exception as e:  # 한 지표 실패가 전체를 막지 않도록
            print(f"[warn] {ind.key} ({ind.code}) 수집 실패: {type(e).__name__}: {e}")

    df = pd.DataFrame(frames)
    # 저빈도(분기 GDP 등) 결측은 직전값으로 채움
    df = df.resample("ME").mean().ffill()
    return df


def load():
    """캐시 우선 로드. parquet 없으면 라이브 수집."""
    if os.path.exists(PARQUET):
        try:
            return pd.read_parquet(PARQUET)
        except Exception as e:
            print(f"[warn] parquet 읽기 실패, 라이브 수집으로 대체: {e}")
    return fetch_all()
