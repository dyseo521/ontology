# OntoQuant — 온톨로지 기반 퀀트 포트폴리오 리스크

종목·팩터·익스포저·이벤트(공시/실적/매크로)를 **온톨로지 그래프**로 연결하고,
**"이 이벤트가 내 포트폴리오 어디에 전파되나"** 를 추적하며, 백테스트로 검증된
리밸런싱 제안과 인사이트를 제공합니다.

- 대시보드: https://dyseo521.github.io/ontology/
- 스택: Python 파이프라인 + Next.js 정적 대시보드 + Claude Code MCP + GitHub Actions

## 핵심 개념

- **Semantic layer**: `ontology/*.yaml` 이 단일 진실 소스 — 13개 Object Type
  (Instrument/Portfolio/Position/Factor/Event 4종/Insight/Proposal/Decision/Model…),
  2개 인터페이스, 15개 링크 타입.
- **Kinetic layer**: 모든 상태 변경은 액션(파라미터 + 제출 기준 + 규칙 + 사이드 이펙트)을
  통해서만 — 실패 사유가 메시지로 반환되고 전 과정이 감사 로그에 남습니다.
- **검증 우선**: 인사이트·제안은 증거(이벤트 스터디, 백테스트)가 게이트를 통과해야
  "검증됨" 배지를 받습니다.
- **시나리오**: 온톨로지를 fork한 샌드박스에서 what-if를 계산하고, 만족할 때만 커밋.
- **결정 기록**: 추천값·근거·백테스트 스냅샷과 사람의 결정·사유를 함께 보존.

## 구조

```
ontology/     스키마 (YAML) → Python 로더 + TypeScript codegen
pipeline/     ontoquant: ingest → compute → events → propagation → insights → proposals → export
mcp-server/   Claude Code 연동 MCP 서버 (조회/RAG/액션/시나리오/publish 17개 도구)
dashboard/    Next.js 정적 대시보드 (9개 라우트, DESIGN.md 디자인 시스템)
data/         계층형 정본: source(수집) / computed(파생) / writeback(편집·결정)
```

## 검증 체계

| 대상 | 방법 | 게이트 |
|---|---|---|
| 이벤트 인사이트 | 시장모형 CAR[-1,+5] 이벤트 스터디 (3년+ 표본) | n ≥ 10 AND \|t\| ≥ 2 |
| 리밸런싱 제안 | vectorbt 3년 walk-forward (거래비용 KR 10bp/US 5bp) | Sharpe > 베이스라인 AND MDD ≤ ×1.1 |
| 팩터 모델 | 롤링 OLS 품질 (일일) | median R² ≥ 0.15 AND coverage 100% |

게이트를 통과하지 못한 제안은 승인 자체가 차단됩니다 (제출 기준이 강제).

## 빠른 시작

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e "pipeline[ml,backtest,dev]" -e mcp-server

# api-key.txt (git 미추적): FRED_API_KEY=... / DART_API_KEY=... / TIINGO_API_KEY=...

.venv/bin/python -m ontoquant.seed
.venv/bin/python -m ontoquant.run_daily --stage all
.venv/bin/python -m ontoquant.events.backfill --years 3   # 이벤트 스터디 표본 (1회)

cd dashboard && npm ci && npm run build
python3 -m http.server 8899 -d out    # http://localhost:8899

.venv/bin/python -m pytest pipeline/tests
```

## Claude Code MCP

레포 루트 `.mcp.json` 으로 자동 인식. 대표 흐름:

1. `get_insights` / `search_similar_events("유상증자 이후 주가")` — RAG + CAR 근거
2. `propose_rebalance(...)` — 제안 생성 → 자동 백테스트 → PENDING
3. `record_decision(id, "APPROVE", 사유)` — 결재 (게이트 미통과·한도 위반은 차단됨)
4. `run_scenario` → `scenario_apply` → `compare_scenario` → `commit_scenario`
5. `publish("메시지")` — 커밋+푸시 → Pages 재배포

## 자동화

1. Settings → Pages → Source: **GitHub Actions**
2. Settings → Secrets → Actions: `FRED_API_KEY`, `DART_API_KEY`, `TIINGO_API_KEY`
3. `daily.yml` 이 평일 KST 08:30 수집→계산→커밋→배포 (`deploy.yml` 은 수동 publish 경로)

## 데이터 소스

Naver Finance(KR 주가) · Tiingo(US 주가) · FRED(매크로) · Ken French(팩터) ·
DART(KR 공시) · SEC EDGAR(8-K) · Yahoo RSS(뉴스)

> ⚠️ 산출물은 투자 조언이 아니며, 샘플 포트폴리오 기준의 연구/데모 목적입니다.
