"""investing.com 차트 JSON에서 최신 ISM PMI를 받아 data/pmi_manual.csv에 추가.

공개 차트 엔드포인트(sbcharts.investing.com, 이벤트 173 = ISM 제조업 PMI)를
월 1회 조회해 아직 없는 참조월만 추가한다. 엔드포인트가 막히거나 형식이
바뀌어도 경고만 내고 종료 → 웹 입력폼/CSV 직접 편집 폴백이 항상 유효.

실행: python scripts/update_pmi.py
"""

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

from src.fetch import MANUAL_PMI, upsert_manual_pmi  # noqa: E402

URL = "https://sbcharts.investing.com/events_charts/us/173.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Referer": "https://www.investing.com/economic-calendar/ism-manufacturing-pmi-173",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.investing.com",
}


def fetch_latest(n=3):
    """최근 n개 발표의 (참조월 YYYY-MM, 값) 목록."""
    req = urllib.request.Request(URL, headers=HEADERS)
    data = json.loads(urllib.request.urlopen(req, timeout=30).read())
    rows = [r for r in data.get("attr", []) if r.get("actual") is not None]
    out = []
    for r in rows[-n:]:
        rel = pd.Timestamp(r["timestamp"], unit="ms")
        # 발표일은 매월 1~5일: +4일 보정으로 월말 타임스탬프 에지 방어 후
        # 발표월 - 1 = 참조월
        ref = ((rel + pd.Timedelta(days=4)).to_period("M") - 1).strftime("%Y-%m")
        val = float(r["actual"])
        if not (20 < val < 80):  # 값 오염 방어
            raise ValueError(f"PMI 값 이상: {ref}={val}")
        out.append((ref, val))
    return out


def main():
    existing = pd.read_csv(MANUAL_PMI).dropna()
    have = set(pd.to_datetime(existing["date"]).dt.strftime("%Y-%m"))
    added = []
    for month, val in fetch_latest():
        if month not in have:
            upsert_manual_pmi(month, val)
            added.append(f"{month}={val}")
    print("PMI added:", ", ".join(added) if added else "none (up to date)")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # 자동 수집 실패는 치명적이지 않음 — 수동 입력 폴백 유지
        print(f"[warn] PMI auto-fetch failed ({type(e).__name__}: {e}) — manual fallback")
