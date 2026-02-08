"use client";

import { useState } from "react";
import { useApi } from "@/lib/hooks";
import { fetchApi, TickerView } from "@/lib/api";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

const TICKERS = [
  "AAPL", "TSLA", "NVDA", "MSFT", "AMZN", "GOOGL", "META", "AMD", "NFLX", "JPM",
];

export default function TickerPage() {
  const [ticker, setTicker] = useState("AAPL");
  const { data, loading } = useApi<TickerView>(
    `/api/ticker/${ticker}`,
    10000
  );

  const sentimentData = data?.sentiments
    ?.slice()
    .reverse()
    .map((s) => ({
      time: s.created_at
        ? new Date(s.created_at).toLocaleTimeString()
        : "",
      score: s.score,
      confidence: s.confidence,
    })) ?? [];

  const coverageData = data?.coverage
    ?.slice()
    .reverse()
    .map((c) => ({
      time: c.created_at
        ? new Date(c.created_at).toLocaleTimeString()
        : "",
      coverage: c.coverage_score,
      sources: c.distinct_sources,
      mentions: c.mention_count,
    })) ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <h2 className="text-2xl font-bold">Ticker View</h2>
        <div className="flex gap-1 flex-wrap">
          {TICKERS.map((t) => (
            <button
              key={t}
              className={`px-2 py-1 rounded text-xs font-mono ${
                ticker === t
                  ? "bg-blue-600 text-white"
                  : "bg-slate-800 text-slate-400 hover:text-white"
              }`}
              onClick={() => setTicker(t)}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {loading && !data && (
        <p className="text-slate-500">Loading...</p>
      )}

      {data && (
        <>
          {/* Candidate status */}
          {data.candidate ? (
            <div className="card">
              <h3 className="text-sm text-slate-400 mb-1">Active Candidate</h3>
              <div className="flex items-center gap-3">
                <span className="text-xl font-mono font-bold">{ticker}</span>
                <span
                  className={`badge text-sm ${
                    data.candidate.direction === "bullish"
                      ? "badge-bullish"
                      : "badge-bearish"
                  }`}
                >
                  {data.candidate.direction}
                </span>
                <span className="font-mono">
                  Urgency: {data.candidate.urgency?.toFixed(1)}
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-1">
                {data.candidate.rationale}
              </p>
            </div>
          ) : (
            <div className="card text-slate-500 text-sm">
              {ticker} is not currently an active candidate.
            </div>
          )}

          {/* Sentiment chart */}
          {sentimentData.length > 0 && (
            <div className="card">
              <h3 className="text-sm text-slate-400 mb-3">
                Sentiment Score Over Time
              </h3>
              <ResponsiveContainer width="100%" height={250}>
                <LineChart data={sentimentData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis
                    dataKey="time"
                    tick={{ fill: "#94a3b8", fontSize: 10 }}
                  />
                  <YAxis
                    domain={[-1, 1]}
                    tick={{ fill: "#94a3b8", fontSize: 10 }}
                  />
                  <Tooltip
                    contentStyle={{
                      background: "#1e293b",
                      border: "1px solid #334155",
                    }}
                  />
                  <Line
                    type="monotone"
                    dataKey="score"
                    stroke="#3b82f6"
                    strokeWidth={2}
                    dot={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="confidence"
                    stroke="#22c55e"
                    strokeWidth={1}
                    strokeDasharray="5 5"
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Coverage chart */}
          {coverageData.length > 0 && (
            <div className="card">
              <h3 className="text-sm text-slate-400 mb-3">
                Coverage Metrics Over Time
              </h3>
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={coverageData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis
                    dataKey="time"
                    tick={{ fill: "#94a3b8", fontSize: 10 }}
                  />
                  <YAxis tick={{ fill: "#94a3b8", fontSize: 10 }} />
                  <Tooltip
                    contentStyle={{
                      background: "#1e293b",
                      border: "1px solid #334155",
                    }}
                  />
                  <Line
                    type="monotone"
                    dataKey="coverage"
                    stroke="#f59e0b"
                    strokeWidth={2}
                    dot={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="mentions"
                    stroke="#8b5cf6"
                    strokeWidth={1}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Recent sentiment scores */}
          {data.sentiments.length > 0 && (
            <div className="card">
              <h3 className="text-sm text-slate-400 mb-3">
                Recent Sentiment Scores
              </h3>
              <div className="space-y-1 max-h-60 overflow-auto">
                {data.sentiments.slice(0, 20).map((s, i) => (
                  <div
                    key={i}
                    className="flex items-center gap-2 text-xs bg-slate-900 rounded px-2 py-1"
                  >
                    <span className="text-slate-500 font-mono">
                      {s.created_at
                        ? new Date(s.created_at).toLocaleTimeString()
                        : ""}
                    </span>
                    <span
                      className={`badge ${
                        s.label === "bullish"
                          ? "badge-bullish"
                          : s.label === "bearish"
                          ? "badge-bearish"
                          : "badge-neutral"
                      }`}
                    >
                      {s.label}
                    </span>
                    <span className="font-mono">{s.score?.toFixed(3)}</span>
                    <span className="text-slate-400">
                      conf={s.confidence?.toFixed(2)}
                    </span>
                    {s.tags?.slice(0, 3).map((t, j) => (
                      <span key={j} className="text-slate-500">
                        {t}
                      </span>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Positions */}
          {data.positions.length > 0 && (
            <div className="card">
              <h3 className="text-sm text-slate-400 mb-3">Positions</h3>
              <div className="space-y-1">
                {data.positions.map((p) => (
                  <div
                    key={p.id}
                    className="flex items-center justify-between bg-slate-900 rounded px-3 py-2 text-sm"
                  >
                    <span
                      className={`badge ${
                        p.status === "open" ? "badge-info" : "badge-neutral"
                      }`}
                    >
                      {p.status}
                    </span>
                    <span className="font-mono">
                      Entry: ${p.entry_price?.toFixed(2)}
                    </span>
                    <span
                      className={`font-mono ${
                        (p.unrealized_pnl ?? p.realized_pnl ?? 0) >= 0
                          ? "text-green-400"
                          : "text-red-400"
                      }`}
                    >
                      P/L: $
                      {(p.unrealized_pnl ?? p.realized_pnl ?? 0).toFixed(2)}
                    </span>
                    {p.exit_reason && (
                      <span className="text-xs text-slate-400">
                        {p.exit_reason}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
