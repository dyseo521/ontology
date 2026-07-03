// 빌드 타임 데이터 로더 — public/data/*.json 을 fs 로 읽는다 (정적 export 전용).
import fs from "node:fs";
import path from "node:path";

const DATA_DIR = path.join(process.cwd(), "public", "data");

function readJson<T>(rel: string, fallback: T): T {
  const p = path.join(DATA_DIR, rel);
  if (!fs.existsSync(p)) return fallback;
  return JSON.parse(fs.readFileSync(p, "utf-8")) as T;
}

export interface PositionView {
  positionId: string;
  portfolioId: string;
  instrumentId: string;
  quantity: number;
  avgCostLocal: number;
  lastPriceLocal?: number | null;
  marketValueBase?: number | null;
  weight?: number | null;
  dailyPnlBase?: number | null;
  unrealizedPnlPct?: number | null;
  instrument: {
    name?: string; nameKo?: string; ticker?: string;
    market?: string; sector?: string; currency?: string;
  };
}

export interface PortfolioDoc {
  portfolio: {
    portfolioId: string; name: string; baseCurrency: string; benchmark?: string;
    riskLimits?: { maxWeightPerName?: number; maxVar95?: number; maxSectorWeight?: number; maxHoldings?: number };
    totalValueBase?: number; dailyPnlBase?: number;
  };
  positions: PositionView[];
}

export interface RiskMetric {
  metricId: string; scopeType: string; scopeId: string; metricType: string;
  value: number; asOfDate: string; limitBreached?: boolean; limitValue?: number | null;
}

export interface RiskSeries {
  dates: string[]; totalValueBase: number[];
  drawdown: (number | null)[]; var95: (number | null)[]; vol30: (number | null)[];
}

export interface GraphData {
  nodes: { id: string; objectType: string; pk: string; label: string; props: Record<string, unknown> }[];
  edges: { source: string; target: string; linkType: string; props: Record<string, unknown> }[];
}

export interface InsightView {
  insightId: string; insightType: string; title: string; narrative: string;
  severity: number; confidence?: number | null; validationStatus: string;
  validationSummary?: string | null; evaluationRunId?: string | null;
  sectorId?: string | null;
  recommendedAction?: { label: string; actionApiName?: string | null; paramsPreset?: unknown } | null;
  createdAt: string; asOfDate: string;
}

export interface EventView {
  eventId: string; eventType: string; occurredAt: string; title: string;
  summary?: string | null; severity?: number | null; sourceUrl?: string | null;
  objectType?: string | null;
  market?: string;
  sentiment?: number | null;
  sentimentLabel?: string | null;
  publisher?: string | null;
  dupCount?: number | null;
  instrumentIds?: string[];
  impact?: {
    portfolioImpactScore: number;
    topPositions: { positionId: string; instrumentId: string; label: string; score: number }[];
    paths: unknown[];
  } | null;
}

export interface SectorView {
  sectorId: string; name: string; nameKo?: string; colorToken?: string;
  weight: number;
  members: { instrumentId: string; name?: string; ticker?: string; weight: number; contribVar?: number | null }[];
  contribVar: number;
  recentEvents: number;
  insightIds: string[];
}

export interface ExposuresDoc {
  instruments: {
    instrumentId: string; name?: string; weight: number;
    exposures: Record<string, { beta: number; tStat?: number; r2?: number; stale?: boolean }>;
  }[];
  portfolio: Record<string, number>;
}

export interface ModelView {
  modelVersionId: string; modelId: string; version: string; stage: string;
  params?: Record<string, unknown>; description?: string; createdAt: string;
  evaluationRuns: EvaluationRunView[];
}

export interface EvaluationRunView {
  runId: string; modelVersionId: string; runType: string;
  metricSet: Record<string, unknown>;
  datasetRange?: { start: string; end: string };
  passedGates: boolean;
  gateResults: { gate: string; passed: boolean; detail?: string }[];
  createdAt: string;
}

export interface ProposalView {
  proposalId: string; title: string; status: string; rationale: string;
  createdAt: string; createdBy: string; asOfDate: string;
  legs: { instrumentId: string; side: string; targetWeightDelta: number; estQuantity?: number | null; reason?: string | null }[];
  expectedImpact?: Record<string, number | null> | null;
  backtestRunId?: string | null;
  backtest?: EvaluationRunView | null;
}

export interface DecisionView {
  decisionId: string; subjectType: string; subjectId: string; decidedBy: string;
  decidedAt: string; decision: string; reason: string;
  recommendationSnapshot?: Record<string, unknown> | null;
}

export interface Meta {
  asOf: string | null; generatedAt: string;
  sources: Record<string, { status?: string; added?: number } | Record<string, unknown>>;
  counts: Record<string, number>;
}

export interface SchemaDoc {
  objectTypes: { apiName: string; displayName: string; color?: string; icon?: string; description?: string }[];
  interfaces: { apiName: string; displayName: string; color?: string; implementedBy: string[] }[];
  linkTypes: { apiName: string; displayName?: string; from: string; to: string; cardinality: string }[];
}

export interface ScenarioView {
  scenarioId: string; name: string; baseDate: string; status: string;
  appliedActionIds: string[]; diffSummary?: DiffSummary | null; createdAt: string;
}

export interface DiffSummary {
  positions?: { added: string[]; removed: string[]; changed: { positionId: string; field: string; base: number; scenario: number }[] };
  metrics?: Record<string, { base: number | null; scenario: number | null; delta: number | null }>;
  exposures?: Record<string, { base: number; scenario: number; delta: number }>;
}

export const loadMeta = () => readJson<Meta>("meta.json", { asOf: null, generatedAt: "", sources: {}, counts: {} });
export const loadPortfolio = () => readJson<PortfolioDoc>("portfolio.json", { portfolio: { portfolioId: "main", name: "", baseCurrency: "KRW" }, positions: [] });
export const loadRiskMetrics = () => readJson<RiskMetric[]>("risk_metrics.json", []);
export const loadRiskSeries = () => readJson<RiskSeries | null>("risk_series.json", null);
export const loadGraph = () => readJson<GraphData>("graph.json", { nodes: [], edges: [] });
export const loadInsights = () => readJson<InsightView[]>("insights.json", []);
export const loadEvents = () => readJson<EventView[]>("events.json", []);
export const loadExposures = () => readJson<ExposuresDoc>("exposures.json", { instruments: [], portfolio: {} });
export const loadModels = () => readJson<ModelView[]>("models.json", []);
export const loadProposals = () => readJson<ProposalView[]>("proposals.json", []);
export const loadDecisions = () => readJson<{ decisions: DecisionView[]; actionLog: Record<string, unknown>[] }>("decisions.json", { decisions: [], actionLog: [] });
export const loadSchemaDoc = () => readJson<SchemaDoc>("schema.json", { objectTypes: [], interfaces: [], linkTypes: [] });
export const loadScenarios = () => readJson<ScenarioView[]>("scenarios.json", []);
export const loadSectors = () => readJson<SectorView[]>("sectors.json", []);
export const loadInstruments = () => readJson<InstrumentMaster[]>("instruments.json", []);
export const loadSignals = () => readJson<SignalsDoc | null>("signals.json", null);

export interface SignalsDoc {
  asOf: string;
  board: {
    instrumentId: string; name: string; ticker: string;
    held: boolean; tradable: boolean;
    direction: "BUY" | "SELL"; signal: number; expected5d: number;
    strength: number; evidenceShare: number; conviction: number;
    strengthNote?: string | null;
    evidence: { eventId: string; eventType: string; validated: boolean }[];
  }[];
  audit: Record<string, {
    meanIC?: number; icTstat?: number; hitRateStrong?: number | null;
    nObs?: number; byYear?: Record<string, unknown>;
  } | null>;
  sourceValidity?: { useful: string[]; weak: string[] };
}

export interface InstrumentMaster {
  instrumentId: string; ticker: string; name: string; nameKo?: string;
  market: string; currency: string; assetClass: string;
  sectorId?: string; sector?: string; tradable: boolean;
}

export function loadPrices(instrumentId: string): { instrumentId: string; dates: string[]; close: number[] } | null {
  return readJson(path.join("prices", `${instrumentId.replace(/:/g, "_")}.json`), null as never);
}

export function loadBacktest(runId: string): { runId: string; dates: string[]; strategy: number[]; baseline: number[] } | null {
  return readJson(path.join("backtests", `${runId}.json`), null as never);
}
