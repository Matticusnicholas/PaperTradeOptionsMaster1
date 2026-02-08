"use client";

import { useState } from "react";
import { useApi } from "@/lib/hooks";
import { CandidateItem, OptionContractItem } from "@/lib/api";

export default function OptionsPage() {
  const { data: candidates } = useApi<CandidateItem[]>(
    "/api/candidates?status=active&limit=10",
    10000
  );
  const { data: contracts } = useApi<OptionContractItem[]>(
    "/api/options/contracts?limit=200",
    15000
  );
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);

  const tickerContracts = contracts?.filter(
    (c) => !selectedTicker || c.ticker === selectedTicker
  );

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Options Decision</h2>

      {/* Candidate selector */}
      <div className="flex gap-2 flex-wrap">
        <button
          className={`px-3 py-1 rounded text-sm ${
            !selectedTicker
              ? "bg-blue-600 text-white"
              : "bg-slate-800 text-slate-400"
          }`}
          onClick={() => setSelectedTicker(null)}
        >
          All
        </button>
        {candidates?.map((c) => (
          <button
            key={c.id}
            className={`px-3 py-1 rounded text-sm ${
              selectedTicker === c.ticker
                ? "bg-blue-600 text-white"
                : "bg-slate-800 text-slate-400"
            }`}
            onClick={() => setSelectedTicker(c.ticker)}
          >
            {c.ticker}{" "}
            <span
              className={
                c.direction === "bullish" ? "text-green-400" : "text-red-400"
              }
            >
              ({c.direction})
            </span>
          </button>
        ))}
      </div>

      {/* Contracts table */}
      {tickerContracts && tickerContracts.length > 0 ? (
        <div className="overflow-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-slate-400 border-b border-slate-700">
                <th className="py-2 px-1">Symbol</th>
                <th className="py-2 px-1">Type</th>
                <th className="py-2 px-1">Strike</th>
                <th className="py-2 px-1">Expiry</th>
                <th className="py-2 px-1">DTE</th>
                <th className="py-2 px-1">Bid</th>
                <th className="py-2 px-1">Ask</th>
                <th className="py-2 px-1">IV</th>
                <th className="py-2 px-1">Delta</th>
                <th className="py-2 px-1">Gamma</th>
                <th className="py-2 px-1">Theta</th>
                <th className="py-2 px-1">Vega</th>
                <th className="py-2 px-1">Score</th>
              </tr>
            </thead>
            <tbody>
              {tickerContracts.map((c) => (
                <tr
                  key={c.id}
                  className={`border-b border-slate-800 hover:bg-slate-800/50 ${
                    c.score && c.score > 20
                      ? "bg-green-900/10"
                      : ""
                  }`}
                >
                  <td className="py-1 px-1 font-mono">{c.contract_symbol?.slice(-15)}</td>
                  <td className="py-1 px-1">
                    <span
                      className={`badge ${
                        c.option_type === "call"
                          ? "badge-bullish"
                          : "badge-bearish"
                      }`}
                    >
                      {c.option_type}
                    </span>
                  </td>
                  <td className="py-1 px-1 font-mono">{c.strike?.toFixed(1)}</td>
                  <td className="py-1 px-1">{c.expiry}</td>
                  <td className="py-1 px-1 font-mono">{c.dte}</td>
                  <td className="py-1 px-1 font-mono">{c.bid?.toFixed(2)}</td>
                  <td className="py-1 px-1 font-mono">{c.ask?.toFixed(2)}</td>
                  <td className="py-1 px-1 font-mono">
                    {c.iv ? (c.iv * 100).toFixed(1) + "%" : "-"}
                  </td>
                  <td className="py-1 px-1 font-mono">{c.delta?.toFixed(3)}</td>
                  <td className="py-1 px-1 font-mono">{c.gamma?.toFixed(4)}</td>
                  <td className="py-1 px-1 font-mono text-red-400">
                    {c.theta?.toFixed(4)}
                  </td>
                  <td className="py-1 px-1 font-mono">{c.vega?.toFixed(4)}</td>
                  <td className="py-1 px-1 font-mono font-bold">
                    {c.score != null ? (
                      <span
                        className={
                          c.score > 20 ? "text-green-400" : "text-slate-400"
                        }
                      >
                        {c.score.toFixed(1)}
                      </span>
                    ) : (
                      "-"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="card text-slate-500 text-sm">
          No option contracts yet. Contracts are fetched during the 30-minute
          decision tick for active candidates.
        </div>
      )}

      {/* Score breakdown for selected */}
      {selectedTicker && tickerContracts && tickerContracts.length > 0 && (
        <div className="card">
          <h3 className="text-lg font-semibold mb-3">Score Breakdown - Top Contracts</h3>
          {tickerContracts
            .filter((c) => c.score != null)
            .sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
            .slice(0, 5)
            .map((c) => (
              <div key={c.id} className="bg-slate-900 rounded p-3 mb-2">
                <div className="flex items-center gap-2 mb-2">
                  <span className="font-mono text-sm">{c.contract_symbol}</span>
                  <span className="font-mono font-bold text-green-400">
                    Score: {c.score?.toFixed(1)}
                  </span>
                </div>
                {c.score_breakdown && (
                  <div className="grid grid-cols-4 gap-2 text-xs">
                    {Object.entries(c.score_breakdown).map(([k, v]) => (
                      <div key={k}>
                        <span className="text-slate-400">{k}:</span>{" "}
                        <span
                          className={`font-mono ${
                            v >= 0 ? "text-green-400" : "text-red-400"
                          }`}
                        >
                          {typeof v === "number" ? v.toFixed(2) : v}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
        </div>
      )}
    </div>
  );
}
