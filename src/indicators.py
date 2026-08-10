"""경기 국면 판단에 쓰는 지표 정의 (미국 기준).

각 지표는 FRED 시리즈(키 없는 pandas-datareader), yfinance 티커,
또는 수동 CSV(manual)로 수집한다.

- group     : leading(선행) / coincident(동행) / lagging(후행) / aux(보조, 합성 미포함)
- source    : "fred" | "yahoo" | "manual"
- transform : 표준화 전 변환  ("yoy" = 전년동월비 %, "level" = 원값)
- invert    : 경기와 반대로 움직이는 지표(실업률 등)는 True

※ PMI 관련 메모
  제조업 선행신호는 실제 ISM PMI('pmi_manual')를 쓴다. data/pmi_manual.csv에
  1959-01~현재가 채워져 있고(FRED-MD 2015-07 빈티지 + investing.com 이력),
  신규 발표분은 scripts/update_pmi.py가 매월 자동 수집한다.
  ISM을 무료로 못 구하던 시절 대체재로 쓰던 지역 연준 서베이(필라델피아
  GACDFSA066MSFRBPHI, 엠파이어스테이트 GACDISA066MSFRBNY)는 실제 ISM 확보 후
  중복이라 제거했다.
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
    Indicator("pmi_manual",   "제조업 PMI(ISM)",       "leading", "manual", "pmi_manual",         "level", note="1959~, 자동수집"),
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
