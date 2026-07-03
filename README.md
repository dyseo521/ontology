# OntoQuant

내 포트폴리오에 닿는 모든 신호를 하나의 그래프로 연결합니다.
공시, 뉴스, 시장 지표가 어느 종목을 거쳐 내 돈까지 오는지 추적하고,
근거가 검증된 제안만 승인으로 이어집니다.

- 대시보드: https://dyseo521.github.io/ontology/
- 스택: Python 파이프라인, Next.js 정적 대시보드, Claude Code MCP, GitHub Actions

## 무엇을 하나

- **연결**: 종목 26개(KR 13 + US 13), 11개 섹터, 기업 정보, 분기 재무, 공시,
  뉴스(네이버, KR-FinBERT 감성 분석)를 하나의 온톨로지 그래프로 묶습니다.
- **추적**: 이벤트가 발생하면 종목, 섹터, 포지션을 거쳐 포트폴리오까지
  전파 경로와 영향 크기를 계산합니다.
- **제안**: 한도 초과나 위험 신호가 잡히면 매수·매도 제안을 만듭니다.
  "IT 비중 5%p 줄이기", "현금 확보" 같은 대응까지 붙습니다.
- **검증**: 모든 제안은 과거 3년으로 미리 돌려보고, 통과 못 하면 승인이 막힙니다.
- **기록**: 누가 왜 승인했는지, 그 결정이 실제로 나았는지까지 계속 추적합니다.

## 과적합을 어떻게 막나

결과를 미리 안 채로 과거를 돌려보는 실수(결과론적 학습)를 구조적으로 차단합니다.

| 장치 | 내용 |
|---|---|
| 시점 고정(PIT) | 과거의 판단은 그 시점까지 알려진 통계만 사용. 이벤트별 원장에 "언제 알 수 있었나"를 기록 |
| 미래 구간 검증 | 전략은 정한 뒤 본 적 없는 구간에서만 채점 (purged walk-forward, 완충 26거래일) |
| 시도 벌점 | 시도한 전략 조합이 많을수록 통과 기준이 자동 상승 (Deflated Sharpe, 시도 장부는 지울 수 없음) |
| 통계 검정 | 이벤트 반응은 표준화 검정(BMP)에 실적 시즌 군집 보정(KP)까지 거쳐야 "검증됨" |
| 결정 추적 | 승인한 제안의 20/60일 뒤 실제 성과를 기록해 적중률이 낮아지면 경고 |

## 빠른 시작

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e "pipeline[ml,backtest,dev]" -e mcp-server

# api-key.txt 작성 (git에 올라가지 않음)
# FRED_API_KEY=... / DART_API_KEY=... / TIINGO_API_KEY=...

.venv/bin/python -m ontoquant.seed
.venv/bin/python -m ontoquant.run_daily --stage all
.venv/bin/python -m ontoquant.events.backfill --years 3   # 최초 1회

cd dashboard && npm ci && npm run build
python3 -m http.server 8899 -d out   # http://localhost:8899

.venv/bin/python -m pytest pipeline/tests
```

## Claude Code에서 쓰기

레포의 `.mcp.json`을 Claude Code가 자동 인식합니다. 대표 흐름:

1. `get_insights` 로 지금 확인할 것을 보고
2. `search_similar_events("유상증자 이후 주가")` 로 과거 유사 사례와 반응을 찾고
3. `propose_rebalance(...)` 로 제안을 만들면 자동으로 검증이 돌고
4. `record_decision(id, "APPROVE", 사유)` 로 결재하면 포트폴리오에 반영됩니다
5. `run_scenario` 로 실제 반영 전에 미리 계산해 볼 수 있습니다

## 자동화

1. GitHub 저장소 Settings에서 Pages Source를 **GitHub Actions**로
2. Secrets에 `FRED_API_KEY`, `DART_API_KEY`, `TIINGO_API_KEY` 등록
3. 평일 아침 8:30(KST)마다 수집, 계산, 배포가 자동으로 돕니다

## 데이터

Naver Finance(KR 시세·뉴스) · Tiingo(US 시세) · FRED(금리·환율·변동성) ·
Ken French(팩터) · DART(공시·재무) · SEC EDGAR(8-K·재무)

> 이 시스템의 산출물은 투자 조언이 아닙니다. 샘플 포트폴리오 기준의 연구·데모입니다.
