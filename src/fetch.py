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
    # 월봉(interval=1mo)은 과거 구간이 잘리는 경우가 있어 일봉으로 받는다
    # (이후 공통 resample("ME")에서 월간화됨)
    df = yf.download(code, start=start, interval="1d", progress=False, auto_adjust=True)
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


def fetch_all(start="1975-01-01"):
    """모든 지표를 받아 월말 기준 단일 DataFrame으로 반환.

    1975년 시작 근거: 선행(S&P500·필라델피아연준 1968~·금리차 1976~·심리 1978~,
    이전은 분기→ffill), 동행(산업생산·가동률), 후행(전부 1964~ 이전) 확보 가능.
    소매판매·수출(1992~)·엠파이어(2001~)는 없는 기간엔 합성에서 자동 제외.
    """
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
    df = df.resample("ME").mean()
    # 내부 결측(분기 GDP, 옛 분기 심리지수 등)은 직전값으로 채우되,
    # 각 지표의 마지막 실제 관측 이후(=아직 미발표 달)는 채우지 않는다.
    # 안 그러면 발표가 늦는 지표의 최신월이 이전 값 복제로 조작됨
    # (예: 심리지수 5월 44.8이 6월에도 44.8로 복제 — 실제 6월은 49.5였음).
    last_valid = {c: df[c].last_valid_index() for c in df.columns}
    df = df.ffill()
    for c in df.columns:
        if c == "gdp":  # 분기 시리즈는 다음 분기까지 직전값 유지가 의도된 동작
            continue
        lv = last_valid[c]
        if lv is not None:
            df.loc[df.index > lv, c] = float("nan")
    # 진행 중인 달은 일간 시리즈 며칠치만 담긴 부분월이라 제외
    df = df[df.index < pd.Timestamp.today().normalize().replace(day=1)]
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
