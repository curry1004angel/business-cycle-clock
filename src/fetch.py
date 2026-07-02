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
    """캐시 우선 로드. parquet 없으면 라이브 수집.

    수동 PMI는 parquet 갱신 주기(월 1회)와 무관하게 항상 CSV 최신값을
    덮어써서 입력 즉시 반영되게 한다.
    """
    if os.path.exists(PARQUET):
        try:
            df = pd.read_parquet(PARQUET)
        except Exception as e:
            print(f"[warn] parquet 읽기 실패, 라이브 수집으로 대체: {e}")
            return fetch_all()
        try:
            s = _manual_pmi().resample("ME").mean()
            df = df.drop(columns=["pmi_manual"], errors="ignore")
            df = df.join(s.rename("pmi_manual"), how="left")
        except Exception:
            pass  # 수동 PMI 없으면 그대로
        return df
    return fetch_all()


def upsert_manual_pmi(month, value):
    """data/pmi_manual.csv 에 해당 월(YYYY-MM) 값을 추가/갱신하고 CSV 전문을 반환."""
    if os.path.exists(MANUAL_PMI):
        m = pd.read_csv(MANUAL_PMI).dropna()
    else:
        m = pd.DataFrame(columns=["date", "pmi"])
    m["date"] = m["date"].astype(str).str[:7]
    m = m[m["date"] != month[:7]]
    m.loc[len(m)] = [month[:7], float(value)]
    m = m.sort_values("date")
    m["date"] = m["date"] + "-01"
    os.makedirs(DATA_DIR, exist_ok=True)
    m.to_csv(MANUAL_PMI, index=False)
    return m.to_csv(index=False)
