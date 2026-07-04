"""경기 국면 판단에 쓰는 지표 정의 (미국 기준).

각 지표는 FRED 시리즈(키 없는 pandas-datareader), yfinance 티커,
또는 수동 CSV(manual)로 수집한다.

- group     : leading(선행) / coincident(동행) / lagging(후행) / aux(보조, 합성 미포함)
- source    : "fred" | "yahoo" | "manual"
- transform : 표준화 전 변환  ("yoy" = 전년동월비 %, "level" = 원값)
- invert    : 경기와 반대로 움직이는 지표(실업률 등)는 True

※ PMI 관련 메모
  ISM/S&P Global PMI는 무료로 "장기 + 최신 + 자동"을 동시에 주는 소스가 없다.
  그래서 제조업 선행신호는 FRED에서 자동 수집되는 '지역 연준 서베이'
  (필라델피아 연준 + 엠파이어스테이트)로 대신한다. 둘 다 ISM보다 ~2주 먼저
  발표되어 선행성이 더 빠르다.
  실제 ISM/S&P PMI 헤드라인을 보고 싶으면 data/pmi_manual.csv 에 월 1회 입력하면
  'pmi_manual' 지표로 합성에 함께 반영된다(비워두면 무시).
  → 2026-07: FRED-MD 2015-07 빈티지(Wayback Machine 보존본)에서 실제 ISM PMI
    1959-01~2015-06을 확보해 채워둠. 2015-07 이후는 수동 입력으로 보완.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Indicator:
    key: str
    name_ko: str
    group: str
    source: str
    code: str
    transform: str
    invert: bool = False
    note: str = ""


INDICATORS = [
    # ── 선행지표 ──────────────────────────────────────────────
    Indicator("sp500",        "주가(S&P500)",          "leading", "yahoo",  "^GSPC",              "yoy"),
    Indicator("sentiment",    "소비자심리지수",         "leading", "fred",   "UMCSENT",            "level"),
    Indicator("yield_spread", "장단기금리차(10Y-2Y)",   "leading", "fred",   "T10Y2Y",             "level"),
    Indicator("philly_fed",   "필라델피아 연준 제조업",  "leading", "fred",   "GACDFSA066MSFRBPHI", "level", note="PMI 대체(서베이)"),
    Indicator("empire_state", "엠파이어스테이트 제조업", "leading", "fred",   "GACDISA066MSFRBNY",  "level", note="PMI 대체(서베이)"),
    Indicator("pmi_manual",   "ISM/S&P PMI(수동)",     "leading", "manual", "pmi_manual",         "level", note="선택 입력"),
    # ── 동행지표 ──────────────────────────────────────────────
    Indicator("indpro",       "산업생산",              "coincident", "fred", "INDPRO",  "yoy"),
    Indicator("retail",       "소매판매",              "coincident", "fred", "RSAFS",   "yoy"),
    Indicator("caputil",      "설비가동률",            "coincident", "fred", "TCU",     "level"),
    Indicator("exports",      "수출",                  "coincident", "fred", "BOPTEXP", "yoy"),
    # ── 후행지표 ──────────────────────────────────────────────
    Indicator("gdp",          "실질GDP",               "lagging", "fred", "GDPC1",   "yoy"),
    Indicator("unemploy",     "실업률",                "lagging", "fred", "UNRATE",  "level", invert=True),
    Indicator("wages",        "임금(시간당)",           "lagging", "fred", "AHETPI",  "yoy"),
    Indicator("hours",        "주당노동시간",           "lagging", "fred", "AWHMAN",  "level"),
]

# 합성에는 미포함. 침체 음영 표시 / 향후 물가축 확장용.
AUX = [
    Indicator("nber_rec", "NBER 침체", "aux", "fred", "USREC",    "level"),
    Indicator("cpi",      "CPI",       "aux", "fred", "CPIAUCSL", "yoy"),
]

GROUP_KO = {"leading": "선행지표", "coincident": "동행지표", "lagging": "후행지표"}


def groups():
    """그룹별 지표 key 목록."""
    g = {"leading": [], "coincident": [], "lagging": []}
    for ind in INDICATORS:
        if ind.group in g:
            g[ind.group].append(ind.key)
    return g


def by_key():
    return {ind.key: ind for ind in (INDICATORS + AUX)}
