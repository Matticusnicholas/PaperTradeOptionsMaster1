"use client";

import { useApi } from "@/lib/hooks";
import { useSignalStream } from "@/lib/hooks";
import {
  AccountInfo,
  CandidateItem,
  HealthInfo,
  MarketClockInfo,
  PositionItem,
} from "@/lib/api";

export default function Dashboard() {
  const { data: account } = useApi<AccountInfo>("/api/account", 5000);
  const { data: clock } = useApi<MarketClockInfo>("/api/market-clock", 10000);
  const { data: health } = useApi<HealthInfo>("/api/health", 10000);
  const { data: candidates } = useApi<CandidateItem[]>(
    "/api/candidates?status=active&limit=5",
    8000
  );
  const { data: positions } = useApi<PositionItem[]>(
    "/api/positions?status=open",
    5000
  );
  const events = useSignalStream();

  const clockColor =
    clock?.status === "OPEN_TRADING"
      ? "text-green-400"
      : clock?.status === "OPEN_NO_NEW_ENTRIES"
      ? "text-yellow-400"
      : "text-red-400";

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Dashboard</h2>

      {/* Stats Row */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <StatCard label="Mode" value={health?.mode?.toUpperCase() || "SIGNAL"} color="text-blue-400" />
        <StatCard label="News" value={String(health?.news_count ?? 0)} />
        <StatCard label="Signals" value={String(health?.signal_count ?? 0)} color="text-yellow-400" />
        <StatCard label="Active Candidates" value={String(health?.active_candidates ?? 0)} />
        <StatCard
          label="Social"
          value={health?.social_enabled ? "ON" : "OFF"}
          color={health?.social_enabled ? "text-green-400" : "text-slate-500"}
        />
      </div>

      {/* Account (trade mode) */}
      {health?.mode === "trade" && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard label="Cash" value={fmt$(account?.cash)} />
          <StatCard label="Equity" value={fmt$(account?.equity)} />
          <StatCard
            label="Total P/L"
            value={fmt$(account?.total_pnl)}
            color={
              (account?.total_pnl ?? 0) >= 0 ? "text-green-400" : "text-red-400"
            }
          />
          <StatCard label="Trades" value={String(account?.total_trades ?? 0)} />
        </div>
      )}

      <div className="card flex items-center justify-between">
        <div>
          <span className="text-slate-400 text-sm mr-2">Market Clock:</span>
          <span className={`font-mono font-bold ${clockColor}`}>
            {clock?.status ?? "..."}
          </span>
        </div>
        <div className="text-sm text-slate-400">
          {clock?.current_et
            ? new Date(clock.current_et).toLocaleTimeString("en-US", {
                timeZone: "America/New_York",
              })
            : ""}
          {" ET"}
        </div>
        <div className="flex gap-2">
          <span
            className={`badge ${
              clock?.is_market_open ? "badge-bullish" : "badge-bearish"
            }`}
          >
            {clock?.is_market_open ? "Market Open" : "Market Closed"}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Active Candidates */}
        <div className="card">
          <h3 className="text-lg font-semibold mb-3">Active Candidates</h3>
          {candidates && candidates.length > 0 ? (
            <div className="space-y-2">
              {candidates.map((c) => (
                <div
                  key={c.id}
                  className="flex items-center justify-between bg-slate-900 rounded p-2"
                >
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-bold">{c.ticker}</span>
                    <span
                      className={`badge ${
                        c.direction === "bullish"
                          ? "badge-bullish"
                          : "badge-bearish"
                      }`}
                    >
                      {c.direction}
                    </span>
                    {c.cross_tier_confirmed && (
                      <span className="badge bg-amber-900 text-amber-300 text-xs">XT</span>
                    )}
                    {c.flow_confirmed && (
                      <span className="badge bg-cyan-900 text-cyan-300 text-xs">FL</span>
                    )}
                  </div>
                  <div className="text-right">
                    <div className="text-sm font-mono">
                      Urgency: {c.urgency?.toFixed(1)}
                    </div>
                    <div className="text-xs text-slate-400">
                      Score: {c.sentiment_score?.toFixed(3)} | Conf:{" "}
                      {c.confidence?.toFixed(2)}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-slate-500 text-sm">
              No active candidates yet. Waiting for news signals...
            </p>
          )}
        </div>

        {/* Open Positions (trade mode) or Signal Summary */}
        <div className="card">
          {health?.mode === "trade" ? (
            <>
              <h3 className="text-lg font-semibold mb-3">Open Positions</h3>
              {positions && positions.length > 0 ? (
                <div className="space-y-2">
                  {positions.map((p) => (
                    <div
                      key={p.id}
                      className="flex items-center justify-between bg-slate-900 rounded p-2"
                    >
                      <div>
                        <span className="font-mono font-bold">{p.ticker}</span>
                        <span className="text-xs text-slate-400 ml-2">
                          {p.contract_symbol}
                        </span>
                      </div>
                      <div className="text-right">
                        <div
                          className={`text-sm font-mono ${
                            (p.unrealized_pnl ?? 0) >= 0
                              ? "text-green-400"
                              : "text-red-400"
                          }`}
                        >
                          {fmt$(p.unrealized_pnl)}
                        </div>
                        <div className="text-xs text-slate-400">
                          Entry: ${p.entry_price?.toFixed(2)} | Qty: {p.quantity}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-slate-500 text-sm">No open positions.</p>
              )}
            </>
          ) : (
            <>
              <h3 className="text-lg font-semibold mb-3">Recent Signals</h3>
              {events.filter(
                (e) =>
                  e.event_type === "SIGNAL_ALERT" ||
                  e.event_type === "WATCH_ALERT"
              ).length > 0 ? (
                <div className="space-y-2">
                  {events
                    .filter(
                      (e) =>
                        e.event_type === "SIGNAL_ALERT" ||
                        e.event_type === "WATCH_ALERT"
                    )
                    .slice(0, 5)
                    .map((e, i) => (
                      <div
                        key={i}
                        className="flex items-center justify-between bg-slate-900 rounded p-2"
                      >
                        <div className="flex items-center gap-2">
                          <span className="font-mono font-bold">
                            {e.payload?.ticker || e.ticker}
                          </span>
                          <span
                            className={`badge text-xs ${
                              e.event_type === "SIGNAL_ALERT"
                                ? "badge-warning"
                                : "badge-info"
                            }`}
                          >
                            {e.event_type === "SIGNAL_ALERT" ? "SIGNAL" : "WATCH"}
                          </span>
                          <span
                            className={`badge text-xs ${
                              e.payload?.direction === "bullish"
                                ? "badge-bullish"
                                : "badge-bearish"
                            }`}
                          >
                            {e.payload?.direction === "bullish" ? "CALL" : "PUT"}
                          </span>
                        </div>
                        <span className="text-xs text-slate-500">
                          {e.ts ? new Date(e.ts).toLocaleTimeString() : ""}
                        </span>
                      </div>
                    ))}
                </div>
              ) : (
                <p className="text-slate-500 text-sm">
                  No signals yet. Waiting for confirmed candidates...
                </p>
              )}
            </>
          )}
        </div>
      </div>

      {/* Recent Events */}
      <div className="card">
        <h3 className="text-lg font-semibold mb-3">Recent Events</h3>
        <div className="max-h-64 overflow-auto space-y-1">
          {events.length > 0 ? (
            events.slice(0, 15).map((e, i) => (
              <div
                key={i}
                className="flex items-start gap-2 text-xs bg-slate-900 rounded px-2 py-1"
              >
                <span className="text-slate-500 font-mono whitespace-nowrap">
                  {new Date(e.ts).toLocaleTimeString()}
                </span>
                <span
                  className={`badge ${
                    e.event_type === "SIGNAL_ALERT"
                      ? "badge-warning"
                      : e.event_type === "WATCH_ALERT"
                      ? "bg-purple-900 text-purple-300"
                      : e.severity === "error"
                      ? "badge-error"
                      : e.severity === "warning"
                      ? "badge-warning"
                      : "badge-info"
                  }`}
                >
                  {e.event_type}
                </span>
                {e.ticker && (
                  <span className="font-mono text-blue-400">{e.ticker}</span>
                )}
                <span className="text-slate-400 truncate">
                  {e.module}
                  {e.payload?.title
                    ? ` - ${e.payload.title}`
                    : e.payload?.message
                    ? ` - ${e.payload.message}`
                    : ""}
                </span>
              </div>
            ))
          ) : (
            <p className="text-slate-500 text-sm">
              Connecting to event stream...
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  color = "text-white",
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="card text-center">
      <div className="text-xs text-slate-400 mb-1">{label}</div>
      <div className={`text-xl font-mono font-bold ${color}`}>{value}</div>
    </div>
  );
}

function fmt$(n: number | undefined | null): string {
  if (n == null) return "$0.00";
  return `$${n.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}
