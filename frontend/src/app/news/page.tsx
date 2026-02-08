"use client";

import { useState } from "react";
import { useApi } from "@/lib/hooks";
import { fetchApi, NewsDetail, NewsItem } from "@/lib/api";

const TIER_LABELS: Record<number, string> = {
  1: "T1",
  2: "T2",
  3: "T3",
};
const TIER_COLORS: Record<number, string> = {
  1: "bg-amber-900 text-amber-300",
  2: "bg-slate-700 text-slate-300",
  3: "bg-slate-800 text-slate-500",
};
const SOURCE_TYPE_COLORS: Record<string, string> = {
  rss: "bg-blue-900 text-blue-300",
  reddit: "bg-orange-900 text-orange-300",
  stocktwits: "bg-green-900 text-green-300",
};

export default function NewsPage() {
  const { data: news } = useApi<NewsItem[]>("/api/news?limit=100", 15000);
  const [selected, setSelected] = useState<NewsDetail | null>(null);
  const [filter, setFilter] = useState<string>("all");

  const loadDetail = async (id: number) => {
    const detail = await fetchApi<NewsDetail>(`/api/news/${id}`);
    setSelected(detail);
  };

  const filtered =
    filter === "all"
      ? news
      : news?.filter((n) => n.source_type === filter);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">News Monitor</h2>
        <div className="flex gap-2">
          {["all", "rss", "reddit", "stocktwits"].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1 rounded text-xs transition-colors ${
                filter === f
                  ? "bg-blue-600 text-white"
                  : "bg-slate-800 text-slate-400 hover:bg-slate-700"
              }`}
            >
              {f === "all" ? "All" : f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* News list */}
        <div className="space-y-1 max-h-[calc(100vh-150px)] overflow-auto">
          {filtered && filtered.length > 0 ? (
            filtered.map((n) => (
              <div
                key={n.id}
                className="card cursor-pointer hover:border-blue-500 transition-colors"
                onClick={() => loadDetail(n.id)}
              >
                <div className="text-sm font-medium">{n.title}</div>
                <div className="flex items-center justify-between mt-1">
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs text-slate-400">{n.source}</span>
                    <span
                      className={`px-1.5 py-0.5 rounded text-xs font-mono ${
                        SOURCE_TYPE_COLORS[n.source_type] || SOURCE_TYPE_COLORS.rss
                      }`}
                    >
                      {n.source_type || "rss"}
                    </span>
                    <span
                      className={`px-1.5 py-0.5 rounded text-xs font-mono ${
                        TIER_COLORS[n.source_tier] || TIER_COLORS[2]
                      }`}
                    >
                      {TIER_LABELS[n.source_tier] || "T2"}
                    </span>
                  </div>
                  <span className="text-xs text-slate-500">
                    {n.ts ? new Date(n.ts).toLocaleString() : ""}
                  </span>
                </div>
              </div>
            ))
          ) : (
            <p className="text-slate-500 text-sm p-4">
              No news items yet. Waiting for RSS/Reddit/StockTwits poll...
            </p>
          )}
        </div>

        {/* Detail panel */}
        <div className="card sticky top-0">
          {selected ? (
            <div className="space-y-4">
              <h3 className="text-lg font-semibold">{selected.title}</h3>
              <div className="flex items-center gap-2 text-xs text-slate-400">
                <span>{selected.source}</span>
                <span
                  className={`px-1.5 py-0.5 rounded font-mono ${
                    SOURCE_TYPE_COLORS[selected.source_type] || SOURCE_TYPE_COLORS.rss
                  }`}
                >
                  {selected.source_type}
                </span>
                <span
                  className={`px-1.5 py-0.5 rounded font-mono ${
                    TIER_COLORS[selected.source_tier] || TIER_COLORS[2]
                  }`}
                >
                  Tier {selected.source_tier}
                </span>
                <span>|</span>
                <span>
                  {selected.ts ? new Date(selected.ts).toLocaleString() : ""}
                </span>
                {selected.url && (
                  <a
                    href={selected.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-blue-400 hover:underline"
                  >
                    [link]
                  </a>
                )}
              </div>
              <p className="text-sm text-slate-300">{selected.summary}</p>

              {/* Tickers */}
              {selected.tickers.length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold text-slate-400 mb-1">
                    Resolved Tickers
                  </h4>
                  <div className="flex flex-wrap gap-2">
                    {selected.tickers.map((t, i) => (
                      <span key={i} className="badge badge-info">
                        {t.ticker} (rel: {t.relevance?.toFixed(2)})
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Sentiment */}
              {selected.sentiments.length > 0 && (
                <div className="space-y-2">
                  <h4 className="text-sm font-semibold text-slate-400">
                    Sentiment Analysis
                  </h4>
                  {selected.sentiments.map((s, i) => (
                    <div key={i} className="bg-slate-900 rounded p-3">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="font-mono font-bold">{s.ticker}</span>
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
                        <span className="font-mono text-sm">
                          {s.score?.toFixed(3)}
                        </span>
                      </div>
                      <div className="grid grid-cols-3 gap-2 text-xs mb-2">
                        <div>
                          Confidence:{" "}
                          <span className="font-mono">
                            {s.confidence?.toFixed(2)}
                          </span>
                        </div>
                        <div>
                          Intensity:{" "}
                          <span className="font-mono">
                            {s.intensity?.toFixed(2)}
                          </span>
                        </div>
                      </div>
                      {s.tags && s.tags.length > 0 && (
                        <div className="flex flex-wrap gap-1 mb-2">
                          {s.tags.map((tag, j) => (
                            <span
                              key={j}
                              className="bg-slate-800 text-slate-300 px-1.5 py-0.5 rounded text-xs"
                            >
                              {tag}
                            </span>
                          ))}
                        </div>
                      )}
                      {s.key_phrases && s.key_phrases.length > 0 && (
                        <div className="text-xs text-slate-400 mb-1">
                          Key phrases:{" "}
                          {s.key_phrases.slice(0, 5).join(", ")}
                        </div>
                      )}
                      <div className="text-xs text-slate-500 italic">
                        {s.explanation}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <p className="text-slate-500 text-sm">
              Click a news item to see details, ticker resolution, and sentiment
              breakdown.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
