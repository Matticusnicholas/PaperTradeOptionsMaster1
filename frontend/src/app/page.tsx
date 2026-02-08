"use client";

import { useApi, useEventStream } from "@/lib/hooks";
import {
  AccountInfo,
  CandidateItem,
  MarketClockInfo,
  PositionItem,
} from "@/lib/api";

export default function Dashboard() {
  const { data: account } = useApi<AccountInfo>("/api/account", 5000);
  const { data: clock } = useApi<MarketClockInfo>("/api/market-clock", 10000);
  const { data: candidates } = useApi<CandidateItem[]>(
    "/api/candidates?status=active&limit=5",
    8000
  );
  const { data: positions } = useApi<PositionItem[]>(
    "/api/positions?status=open",
    5000
  );
  const events = useEventStream(20);

  const clockColor =
    clock?.status === "OPEN_TRADING"
      ? "text-green-400"
      : clock?.status === "OPEN_NO_NEW_ENTRIES"
      ? "text-yellow-400"
      : "text-red-400";

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Dashboard</h2>

      {/* Account + Clock */}
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
              clock?.can_enter_new ? "badge-bullish" : "badge-bearish"
            }`}
          >
            {clock?.can_enter_new ? "New Entries OK" : "No New Entries"}
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

        {/* Open Positions */}
        <div className="card">
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
                    e.severity === "error"
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
