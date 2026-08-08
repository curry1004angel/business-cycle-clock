"""최신 ISM 제조업 PMI를 받아 data/pmi_manual.csv에 추가.

소스를 순서대로 시도한다(하나 막히면 다음으로):
  1. 네이버 모바일 검색 — 발표일·참조월·값이 표로 노출. 국내 IP/데이터센터
     모두에서 응답.
  2. investing.com 차트 JSON — 2026-08부터 GitHub Actions IP에 403 반환
     (로컬에선 동작). 보조로만 유지.

전부 실패해도 경고만 내고 종료 → 앱의 웹 입력폼 / CSV 직접 편집 폴백이 유효.

실행: python scripts/update_pmi.py
"""

import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

from src.fetch import MANUAL_PMI, upsert_manual_pmi  # noqa: E402

NAVER_URL = (
    "https://m.search.naver.com/search.naver?where=m&sm=mtb_etc&mra=blNH&qvt=0"
    "&query=%EB%AF%B8%EA%B5%AD%20ISM%20%EC%A0%9C%EC%A1%B0%EC%97%85%20"
    "%EA%B5%AC%EB%A7%A4%EA%B4%80%EB%A6%AC%EC%9E%90%EC%A7%80%EC%88%98(PMI)"
)
NAVER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                  "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile Safari/605.1.15",
    "Accept-Language": "ko-KR,ko;q=0.9",
}
# "'26.08.03. (7월) 55.60 53.30" → 발표일(yy.mm.dd), 참조월, 발표값, 이전값
NAVER_ROW = re.compile(r"'(\d{2})\.(\d{2})\.(\d{2})\.\s*\((\d{1,2})월\)\s*([\d.]+)\s*([\d.]+)")

INVESTING_URL = "https://sbcharts.investing.com/events_charts/us/173.json"
INVESTING_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Referer": "https://www.investing.com/economic-calendar/ism-manufacturing-pmi-173",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.investing.com",
}


def _get(url, headers, timeout=30):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=headers), timeout=timeout).read()


def _check(ref, val):
    if not (20 < val < 80):
        raise ValueError(f"PMI 값 이상: {ref}={val}")
    return ref, val


def from_naver(n=6):
    """네이버 검색 표에서 (참조월 YYYY-MM, 값) 최신 n개."""
    html = _get(NAVER_URL, NAVER_HEADERS).decode("utf-8", "ignore")
    i = html.find("이전발표")
    if i < 0:
        raise ValueError("네이버 표 영역 없음")
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html[i - 500:i + 6000]))
    out = []
    for yy, mm, _dd, refm, actual, _prev in NAVER_ROW.findall(text)[:n]:
        # 발표월 기준 직전월이 참조월 (1월 발표 = 전년 12월분)
        pub = pd.Period(f"20{yy}-{mm}", freq="M")
        ref = pub - 1
        if ref.month != int(refm):  # 표기된 참조월과 불일치 시 신뢰 불가
            raise ValueError(f"참조월 불일치: 발표 {pub} vs 표기 {refm}월")
        out.append(_check(ref.strftime("%Y-%m"), float(actual)))
    if not out:
        raise ValueError("네이버 파싱 결과 없음")
    return out


def from_investing(n=3):
    """investing.com 차트 JSON에서 (참조월 YYYY-MM, 값) 최신 n개."""
    data = json.loads(_get(INVESTING_URL, INVESTING_HEADERS))
    rows = [r for r in data.get("attr", []) if r.get("actual") is not None]
    out = []
    for r in rows[-n:]:
        rel = pd.Timestamp(r["timestamp"], unit="ms")
        # 발표일은 매월 1~5일: +4일 보정 후 발표월 - 1 = 참조월
        ref = ((rel + pd.Timedelta(days=4)).to_period("M") - 1).strftime("%Y-%m")
        out.append(_check(ref, float(r["actual"])))
    return out


def fetch_latest():
    errors = []
    for name, fn in (("naver", from_naver), ("investing", from_investing)):
        try:
            rows = fn()
            print(f"source: {name}")
            return rows
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}: {e}")
    raise RuntimeError(" | ".join(errors))


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
