"use client";

import { useApi } from "@/lib/hooks";
import { CandidateItem } from "@/lib/api";

export default function CandidatesPage() {
  const { data: active } = useApi<CandidateItem[]>(
    "/api/candidates?status=active&limit=20",
    8000
  );
  const { data: all } = useApi<CandidateItem[]>(
    "/api/candidates?limit=50",
    15000
  );

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Candidate Funnel</h2>

      {/* Active candidates */}
      <div>
        <h3 className="text-lg font-semibold mb-3 text-green-400">
          Active Candidates ({active?.length ?? 0})
        </h3>
        {active && active.length > 0 ? (
          <div className="space-y-3">
            {active.map((c) => (
              <CandidateCard key={c.id} candidate={c} />
            ))}
          </div>
        ) : (
          <div className="card text-slate-500 text-sm">
            No active candidates. The funnel produces candidates when news
            signals cross threshold.
            <div className="mt-2 text-xs text-slate-600">
              Thresholds: |sentiment| &ge; 0.65, confidence &ge; 0.75,
              coverage &ge; 3 or sources &ge; 2
            </div>
          </div>
        )}
      </div>

      {/* All candidates history */}
      <div>
        <h3 className="text-lg font-semibold mb-3 text-slate-400">
          Candidate History
        </h3>
        {all && all.length > 0 ? (
          <div className="overflow-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-slate-400 border-b border-slate-700">
                  <th className="py-2 px-2">Ticker</th>
                  <th className="py-2 px-2">Direction</th>
                  <th className="py-2 px-2">Urgency</th>
                  <th className="py-2 px-2">Sentiment</th>
                  <th className="py-2 px-2">Confidence</th>
                  <th className="py-2 px-2">Coverage</th>
                  <th className="py-2 px-2">Signals</th>
                  <th className="py-2 px-2">Status</th>
                  <th className="py-2 px-2">Created</th>
                </tr>
              </thead>
              <tbody>
                {all.map((c) => (
                  <tr
                    key={c.id}
                    className="border-b border-slate-800 hover:bg-slate-800/50"
                  >
                    <td className="py-2 px-2 font-mono font-bold">
                      {c.ticker}
                    </td>
                    <td className="py-2 px-2">
                      <span
                        className={`badge ${
                          c.direction === "bullish"
                            ? "badge-bullish"
                            : "badge-bearish"
                        }`}
                      >
                        {c.direction}
                      </span>
                    </td>
                    <td className="py-2 px-2 font-mono">
                      {c.urgency?.toFixed(1)}
                    </td>
                    <td className="py-2 px-2 font-mono">
                      {c.sentiment_score?.toFixed(3)}
                    </td>
                    <td className="py-2 px-2 font-mono">
                      {c.confidence?.toFixed(2)}
                    </td>
                    <td className="py-2 px-2 font-mono">
                      {c.coverage_score?.toFixed(1)} ({c.distinct_sources} src)
                    </td>
                    <td className="py-2 px-2">
                      <div className="flex gap-1">
                        {c.cross_tier_confirmed && (
                          <span className="badge bg-amber-900 text-amber-300 text-xs">
                            XT
                          </span>
                        )}
                        {c.flow_confirmed && (
                          <span className="badge bg-cyan-900 text-cyan-300 text-xs">
                            FL
                          </span>
                        )}
                        {!c.cross_tier_confirmed && !c.flow_confirmed && (
                          <span className="text-slate-600 text-xs">-</span>
                        )}
                      </div>
                    </td>
                    <td className="py-2 px-2">
                      <span
                        className={`badge ${
                          c.status === "active"
                            ? "badge-info"
                            : c.status === "traded"
                            ? "badge-bullish"
                            : "badge-neutral"
                        }`}
                      >
                        {c.status}
                      </span>
                    </td>
                    <td className="py-2 px-2 text-xs text-slate-400">
                      {c.created_at
                        ? new Date(c.created_at).toLocaleString()
                        : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-slate-500 text-sm">No candidates in history.</p>
        )}
      </div>
    </div>
  );
}

function CandidateCard({ candidate: c }: { candidate: CandidateItem }) {
  const urgencyColor =
    c.urgency >= 70
      ? "text-red-400"
      : c.urgency >= 50
      ? "text-yellow-400"
      : "text-blue-400";

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-3">
          <span className="text-xl font-mono font-bold">{c.ticker}</span>
          <span
            className={`badge text-sm ${
              c.direction === "bullish" ? "badge-bullish" : "badge-bearish"
            }`}
          >
            {c.direction?.toUpperCase()}
          </span>
          {c.cross_tier_confirmed && (
            <span className="badge bg-amber-900 text-amber-300 text-xs">
              CROSS-TIER
            </span>
          )}
          {c.flow_confirmed && (
            <span className="badge bg-cyan-900 text-cyan-300 text-xs">
              FLOW CONFIRMED ({c.flow_score?.toFixed(0)})
            </span>
          )}
        </div>
        <div className={`text-2xl font-mono font-bold ${urgencyColor}`}>
          {c.urgency?.toFixed(0)}
          <span className="text-xs text-slate-400 ml-1">urgency</span>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-4 text-sm mb-3">
        <div>
          <span className="text-slate-400">Sentiment:</span>{" "}
          <span className="font-mono">{c.sentiment_score?.toFixed(3)}</span>
        </div>
        <div>
          <span className="text-slate-400">Confidence:</span>{" "}
          <span className="font-mono">{c.confidence?.toFixed(2)}</span>
        </div>
        <div>
          <span className="text-slate-400">Coverage:</span>{" "}
          <span className="font-mono">{c.coverage_score?.toFixed(1)}</span>
        </div>
        <div>
          <span className="text-slate-400">Sources:</span>{" "}
          <span className="font-mono">{c.distinct_sources}</span>
        </div>
      </div>

      {c.narrative_tags && c.narrative_tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {c.narrative_tags.map((tag, i) => (
            <span
              key={i}
              className="bg-slate-900 text-slate-300 px-2 py-0.5 rounded text-xs"
            >
              {tag}
            </span>
          ))}
        </div>
      )}

      <div className="text-xs text-slate-400 italic">{c.rationale}</div>
    </div>
  );
}
