# 미국 경기 국면 판단 대시보드

선행·동행·후행 지표를 자동 수집해 현재 경기 국면(**회복 / 성장 / 둔화 / 침체**)을
판단하고, 국면별 국가·지수·섹터 로테이션을 추천하는 개인용 Streamlit 앱.

## 판정 로직

선행지표와 후행지표의 **방향(모멘텀)** 2×2 사분면으로 국면을 결정한다.

| | 후행 ↓ | 후행 ↑ |
|---|---|---|
| **선행 ↑** | 회복 | 성장 |
| **선행 ↓** | 침체 | 둔화 |

동행지표는 판정 신뢰도(confidence) 보정에 사용한다.

**노이즈 억제 (1999~2026 백테스트로 선정):**
- 모멘텀 = 합성지수 6개월 평활 후 6개월 변화량
- 중립대: 모멘텀 |z| < 0.10 이면 직전 방향 유지 — 단 **6개월 만료**
  (더 머물면 낡은 방향 대신 현재 부호를 따름; 장기 횡보 구간 오판 방지)
- 확정규칙: 새 국면이 3개월 연속이어야 공식 전환

→ 2000년 이후 전환 34회(평균 9.1개월), **NBER 침체월의 93%를 침체로 포착**
(닷컴·금융위기·2022긴축 진입 모두 NBER 공표보다 빠르거나 근접).
1975년 전체로는 전환 70회·포착 84% — 1980·82·90년 침체도 잡는다.

## 지표 (미국)

| 그룹 | 지표 | 소스 |
|---|---|---|
| 선행 | S&P500, 소비자심리(UMCSENT), 장단기금리차(T10Y2Y), 필라델피아 연준·엠파이어스테이트 제조업 서베이 | Yahoo, FRED |
| 동행 | 산업생산(INDPRO), 소매판매(RSAFS), 설비가동률(TCU), 수출(BOPTEXP) | FRED |
| 후행 | 실질GDP(GDPC1), 실업률(UNRATE), 임금(AHETPI), 주당노동시간(AWHMAN) | FRED |

- **1975년~현재.** 소매판매·수출은 1992~, 엠파이어스테이트는 2001~이며
  없는 기간엔 합성에서 자동 제외된다(1992년 이전은 판정 정밀도 다소 낮음).
- **PMI 메모**: ISM/S&P PMI는 무료로 "장기+최신+자동"을 동시에 주는 소스가 없어,
  더 빨리 발표되는 지역 연준 서베이를 자동 수집한다. 실제 ISM PMI는
  `data/pmi_manual.csv` 에 있으며 **1959-01~2015-06은 FRED-MD 2015-07 빈티지**
  (ISM 요청으로 2015-08부터 제거됨; Wayback Machine 보존본, 1980-05 최저 29.4 등
  실측 대조 검증)로 채워져 있다. 2015-07 이후는 앱의 수동 입력 폼이나
  GitHub에서 CSV 직접 편집으로 보완한다.

## 로컬 실행

```bash
pip install -r requirements.txt
python scripts/update_data.py   # data/series.parquet 생성(선택, 없으면 앱이 라이브 수집)
streamlit run app.py
```

## 배포 (share.streamlit.io)

1. 이 레포를 GitHub에 푸시.
2. https://share.streamlit.io 에서 레포 연결 → `app.py` 지정.
3. (선택) **개인 잠금**: 앱 Settings → Secrets 에 아래 입력
   ```toml
   [auth]
   password = "원하는_비밀번호"
   ```
4. **자동 데이터 갱신**: `.github/workflows/update-data.yml` 가 매월 3일 데이터를
   수집해 `data/series.parquet` 를 레포에 커밋 → 앱이 자동 재배포된다.
   (Settings → Actions → "Read and write permissions" 활성화 필요)

## 구조

```
app.py                     # Streamlit 대시보드
src/indicators.py          # 지표 ↔ FRED/Yahoo 매핑
src/fetch.py               # 데이터 수집 + 캐시 로드
src/composite.py           # 선행/동행/후행 합성·표준화·모멘텀
src/classify.py            # 2×2 국면 판정 + 신뢰도
src/rotation.py            # 국면별 로테이션 표
scripts/update_data.py     # 수집 → parquet 저장
.github/workflows/         # 월간 자동 수집·커밋
data/                      # series.parquet, meta.json, pmi_manual.csv
```

## 한계 (v1)

- 거시지표는 사후 수정(revision)되며, 본 앱은 최신 수정치를 사용한다.
- 국면 경계(모멘텀 0 부근)에서는 월별로 판정이 흔들릴 수 있어 신뢰도로 표시한다.
- 향후: 물가축(CPI) 추가한 2D 인베스트먼트 클락, NBER 대조·로테이션 백테스트.
