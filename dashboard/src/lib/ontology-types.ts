// 자동 생성 파일 — 편집 금지. 원천: ontology/*.yaml
// 재생성: python scripts/codegen_ts.py

/** 결정 — 사람이 내린 결정의 캡처 (추천 스냅샷 + 근거 + 결정). append-only, writeback 계층. */
export interface Decision {
  decisionId: string;
  subjectType: string;
  subjectId: string;
  decidedBy: string;
  decidedAt: string;
  decision: "APPROVE" | "REJECT" | "MODIFY";
  reason: string;
  recommendationSnapshot?: unknown;
}

/** 공시 이벤트 — DART/SEC 공시. Event 인터페이스 구현. */
export interface DisclosureEvent {
  rcpNo?: string;
  corpCode?: string;
  filingType?: string;
  filingDetail?: string;
  market: "KR" | "US";
  eventId: string;
  eventType: string;
  occurredAt: string;
  title: string;
  summary?: string;
  severity?: number;
  sourceUrl?: string;
  embeddingId?: string;
}

/** 실적 이벤트 — 실적 발표 (DART 실적공시 / 8-K item 2.02). Event 인터페이스 구현. */
export interface EarningsEvent {
  period?: string;
  epsActual?: number;
  epsEstimate?: number;
  surprisePct?: number;
  market: "KR" | "US";
  eventId: string;
  eventType: string;
  occurredAt: string;
  title: string;
  summary?: string;
  severity?: number;
  sourceUrl?: string;
  embeddingId?: string;
}

/** 평가 실행 — MetricSet 패턴 — 모델 버전 + 데이터 범위에 바인딩된 평가 결과와 게이트 판정. */
export interface EvaluationRun {
  runId: string;
  modelVersionId: string;
  runType: "FACTOR_QUALITY" | "EVENT_STUDY" | "PROPOSAL_BACKTEST";
  metricSet: unknown;
  datasetRange: { start: string; end: string };
  passedGates: boolean;
  gateResults: ({ gate: string; passed: boolean; detail?: string })[];
  createdAt: string;
}

/** 팩터 — 리스크 팩터 (스타일/시장/매크로). 시계열은 data/source/factors/에 저장. */
export interface Factor {
  factorId: string;
  name: string;
  nameKo?: string;
  factorType: "STYLE" | "MARKET" | "MACRO";
  source: "KEN_FRENCH" | "FRED" | "NAVER" | "COMPUTED";
  sourceSeriesId?: string;
  unit: "RATIO" | "PCT" | "LEVEL";
  transform: "LEVEL" | "DIFF" | "LOGRET" | "PCT_RETURN";
  regressionGroup: "US_STYLE" | "US_MACRO" | "KR_CORE" | "NONE";
  lagForKr?: number;
}

/** 팩터 익스포저 — 종목의 팩터 베타 (롤링 OLS 산출). 파이프라인이 매일 갱신. */
export interface FactorExposure {
  exposureId: string;
  instrumentId: string;
  factorId: string;
  beta: number;
  tStat?: number;
  stderr?: number;
  r2?: number;
  window: number;
  asOfDate: string;
  modelVersionId: string;
  stale?: boolean;
}

/** 인사이트 — 이벤트/리스크에서 도출된 해석. 이벤트 스터디로 검증되어야 VALIDATED. */
export interface Insight {
  insightId: string;
  insightType: "EVENT_IMPACT" | "LIMIT_BREACH" | "EXPOSURE_SHIFT" | "CONCENTRATION" | "FACTOR_MOVE";
  title: string;
  narrative: string;
  severity: number;
  confidence?: number;
  validationStatus: "VALIDATED" | "UNVALIDATED" | "REJECTED";
  validationSummary?: string;
  evaluationRunId?: string;
  createdAt: string;
  asOfDate: string;
}

/** 종목 — 거래 가능한 주식/ETF. 온톨로지 그래프의 중심 노드. */
export interface Instrument {
  instrumentId: string;
  ticker: string;
  name: string;
  nameKo?: string;
  market: "KRX" | "KOSDAQ" | "XNAS" | "XNYS" | "ARCA";
  currency: "KRW" | "USD";
  assetClass: "EQUITY" | "ETF";
  sector?: string;
  dartCorpCode?: string;
  secCik?: string;
  priceSource: "NAVER" | "TIINGO" | "YFINANCE";
}

/** 매크로 이벤트 — FRED 시리즈 급변동 (|z|>=2, 252d). Event 인터페이스 구현. */
export interface MacroEvent {
  seriesId: string;
  value: number;
  change1d?: number;
  zScore: number;
  eventId: string;
  eventType: string;
  occurredAt: string;
  title: string;
  summary?: string;
  severity?: number;
  sourceUrl?: string;
  embeddingId?: string;
}

/** 모델 버전 — Modeling Objective 패턴. 팩터모델/이벤트분류기/리밸런싱전략의 버전과 스테이지. */
export interface ModelVersion {
  modelVersionId: string;
  modelId: "factor-model" | "event-classifier" | "rebalance-strategy";
  version: string;
  stage: "STAGING" | "PRODUCTION" | "ARCHIVED";
  params?: unknown;
  description?: string;
  createdAt: string;
}

/** 뉴스 이벤트 — RSS 뉴스 (Yahoo per-ticker / DART todayRSS). Event 인터페이스 구현. */
export interface NewsEvent {
  publisher?: string;
  feedSource: "YAHOO_RSS" | "DART_RSS";
  tickerHint?: string;
  eventId: string;
  eventType: string;
  occurredAt: string;
  title: string;
  summary?: string;
  severity?: number;
  sourceUrl?: string;
  embeddingId?: string;
}

/** 포트폴리오 — 사용자 포트폴리오. writeback 계층(portfolio.json)이 정본. */
export interface Portfolio {
  portfolioId: string;
  name: string;
  baseCurrency: "KRW" | "USD";
  benchmark?: string;
  riskLimits: { maxWeightPerName: number; maxVar95: number; maxSectorWeight: number };
  totalValueBase?: number;
  dailyPnlBase?: number;
}

/** 포지션 — 포트폴리오 내 단일 종목 보유. quantity는 사용자(writeback) 소유, 평가치는 파이프라인 소유. */
export interface Position {
  positionId: string;
  portfolioId: string;
  instrumentId: string;
  quantity: number;
  avgCostLocal: number;
  openedAt?: string;
  lastPriceLocal?: number;
  marketValueBase?: number;
  weight?: number;
  dailyPnlBase?: number;
  unrealizedPnlPct?: number;
}

/** 리밸런싱 제안 — 매수/매도/보유 제안. ProposedAction 인터페이스 구현. 백테스트 게이트 통과 후 승인 가능. */
export interface RebalanceProposal {
  legs: ({ instrumentId: string; side: "BUY" | "SELL" | "HOLD"; targetWeightDelta: number; estQuantity?: number; reason?: string })[];
  expectedImpact?: { var95Delta?: number; betaDelta?: number; hhiDelta?: number };
  strategyRule?: unknown;
  backtestRunId?: string;
  proposalId: string;
  title: string;
  status: "DRAFT" | "PENDING" | "APPROVED" | "REJECTED" | "EXECUTED" | "EXPIRED";
  rationale: string;
  createdAt: string;
  createdBy: string;
  asOfDate: string;
}

/** 리스크 지표 — 포트폴리오/포지션 스코프의 리스크 측정치. 최신 asOf만 오브젝트로 유지, 시계열은 export로. */
export interface RiskMetric {
  metricId: string;
  scopeType: "PORTFOLIO" | "POSITION";
  scopeId: string;
  metricType: "VAR_95_1D" | "VOL_30D" | "BETA_MKT" | "MDD_1Y" | "HHI" | "CONTRIB_VAR";
  value: number;
  asOfDate: string;
  limitBreached?: boolean;
  limitValue?: number;
}

/** 시나리오 — 온톨로지 fork/sandbox. 액션을 오버레이에 적용해 what-if 분석, commit 또는 discard. */
export interface Scenario {
  scenarioId: string;
  name: string;
  baseDate: string;
  status: "OPEN" | "COMMITTED" | "DISCARDED";
  appliedActionIds: string[];
  diffSummary?: unknown;
  createdAt: string;
  createdBy?: string;
}

/** 인터페이스 이벤트 */
export type Event = DisclosureEvent | EarningsEvent | MacroEvent | NewsEvent;

/** 인터페이스 제안된 액션 */
export type ProposedAction = RebalanceProposal;

export type LinkTypeName = "decisionOnProposal" | "eventAffectsInstrument" | "eventDrivesFactor" | "exposureFactor" | "insightAboutInstrument" | "insightFromEvent" | "instrumentExposures" | "metricScopePortfolio" | "metricScopePosition" | "modelEvaluations" | "portfolioPositions" | "positionInstrument" | "proposalFromInsight" | "proposalValidatedBy" | "similarEvent";
export type ObjectTypeName = "Decision" | "DisclosureEvent" | "EarningsEvent" | "EvaluationRun" | "Factor" | "FactorExposure" | "Insight" | "Instrument" | "MacroEvent" | "ModelVersion" | "NewsEvent" | "Portfolio" | "Position" | "RebalanceProposal" | "RiskMetric" | "Scenario";
