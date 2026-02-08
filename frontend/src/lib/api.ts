const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";

export async function fetchApi<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export function createEventSocket(
  onMessage: (event: WSEvent) => void,
  onError?: (err: Event) => void
): WebSocket {
  const ws = new WebSocket(`${WS_URL}/ws/events`);
  ws.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      onMessage(data);
    } catch {}
  };
  ws.onerror = (e) => onError?.(e);
  return ws;
}

export interface WSEvent {
  id?: number;
  ts: string;
  event_type: string;
  ticker?: string;
  module: string;
  severity: string;
  payload: Record<string, any>;
}

export interface NewsItem {
  id: number;
  ts: string;
  source: string;
  url: string;
  title: string;
  summary: string;
}

export interface NewsDetail extends NewsItem {
  text: string;
  tickers: { ticker: string; relevance: number; aliases: string[] }[];
  sentiments: {
    ticker: string;
    label: string;
    score: number;
    confidence: number;
    intensity: number;
    tags: string[];
    key_phrases: string[];
    explanation: string;
  }[];
}

export interface SentimentItem {
  id: number;
  news_id: number;
  ticker: string;
  label: string;
  score: number;
  confidence: number;
  intensity: number;
  tags: string[];
  key_phrases: string[];
  explanation: string;
  created_at: string;
}

export interface CandidateItem {
  id: number;
  ticker: string;
  direction: string;
  urgency: number;
  sentiment_score: number;
  confidence: number;
  coverage_score: number;
  distinct_sources: number;
  rationale: string;
  narrative_tags: string[];
  status: string;
  created_at: string;
  updated_at: string;
}

export interface PositionItem {
  id: number;
  ticker: string;
  contract_symbol: string;
  option_type: string;
  strike: number;
  expiry: string;
  quantity: number;
  entry_price: number;
  current_price: number;
  unrealized_pnl: number;
  realized_pnl: number;
  profit_target: number;
  stop_loss: number;
  status: string;
  exit_reason: string;
  opened_at: string;
  closed_at: string;
}

export interface AccountInfo {
  cash: number;
  equity: number;
  open_positions: number;
  total_trades: number;
  total_pnl: number;
  updated_at: string;
}

export interface MarketClockInfo {
  status: string;
  is_market_open: boolean;
  can_enter_new: boolean;
  is_after_cutoff: boolean;
  current_et: string;
}

export interface HealthInfo {
  status: string;
  news_count: number;
  last_news_at: string | null;
  last_event_at: string | null;
  active_candidates: number;
  open_positions: number;
}

export interface OptionContractItem {
  id: number;
  ticker: string;
  contract_symbol: string;
  option_type: string;
  strike: number;
  expiry: string;
  bid: number;
  ask: number;
  last_price: number;
  volume: number;
  open_interest: number;
  iv: number;
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  dte: number;
  moneyness: number;
  score: number;
  score_breakdown: Record<string, number>;
}

export interface TickerView {
  ticker: string;
  sentiments: {
    score: number;
    label: string;
    confidence: number;
    tags: string[];
    created_at: string;
  }[];
  coverage: {
    coverage_score: number;
    distinct_sources: number;
    mention_count: number;
    created_at: string;
  }[];
  candidate: { direction: string; urgency: number; rationale: string } | null;
  positions: {
    id: number;
    status: string;
    entry_price: number;
    current_price: number;
    unrealized_pnl: number;
    realized_pnl: number;
    exit_reason: string;
  }[];
}
