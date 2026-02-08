"use client";

import { useApi } from "@/lib/hooks";
import { AccountInfo, PositionItem } from "@/lib/api";

export default function TradesPage() {
  const { data: account } = useApi<AccountInfo>("/api/account", 5000);
  const { data: open } = useApi<PositionItem[]>(
    "/api/positions?status=open",
    5000
  );
  const { data: closed } = useApi<PositionItem[]>("/api/trades?limit=50", 10000);

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Trades</h2>

      {/* Account summary */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <Stat label="Cash" value={fmt$(account?.cash)} />
        <Stat label="Equity" value={fmt$(account?.equity)} />
        <Stat
          label="Total P/L"
          value={fmt$(account?.total_pnl)}
          color={(account?.total_pnl ?? 0) >= 0 ? "text-green-400" : "text-red-400"}
        />
        <Stat label="Open" value={String(account?.open_positions ?? 0)} />
        <Stat label="Total Trades" value={String(account?.total_trades ?? 0)} />
      </div>

      {/* Open positions */}
      <div>
        <h3 className="text-lg font-semibold mb-3 text-blue-400">
          Open Positions ({open?.length ?? 0})
        </h3>
        {open && open.length > 0 ? (
          <div className="overflow-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-slate-400 border-b border-slate-700">
                  <th className="py-2 px-2">Ticker</th>
                  <th className="py-2 px-2">Contract</th>
                  <th className="py-2 px-2">Type</th>
                  <th className="py-2 px-2">Qty</th>
                  <th className="py-2 px-2">Entry</th>
                  <th className="py-2 px-2">Current</th>
                  <th className="py-2 px-2">P/L</th>
                  <th className="py-2 px-2">PT</th>
                  <th className="py-2 px-2">SL</th>
                  <th className="py-2 px-2">Opened</th>
                </tr>
              </thead>
              <tbody>
                {open.map((p) => (
                  <tr key={p.id} className="border-b border-slate-800">
                    <td className="py-2 px-2 font-mono font-bold">{p.ticker}</td>
                    <td className="py-2 px-2 font-mono text-xs">
                      {p.contract_symbol}
                    </td>
                    <td className="py-2 px-2">
                      <span
                        className={`badge ${
                          p.option_type === "call" ? "badge-bullish" : "badge-bearish"
                        }`}
                      >
                        {p.option_type}
                      </span>
                    </td>
                    <td className="py-2 px-2 font-mono">{p.quantity}</td>
                    <td className="py-2 px-2 font-mono">
                      ${p.entry_price?.toFixed(2)}
                    </td>
                    <td className="py-2 px-2 font-mono">
                      ${p.current_price?.toFixed(2)}
                    </td>
                    <td
                      className={`py-2 px-2 font-mono font-bold ${
                        (p.unrealized_pnl ?? 0) >= 0
                          ? "text-green-400"
                          : "text-red-400"
                      }`}
                    >
                      {fmt$(p.unrealized_pnl)}
                    </td>
                    <td className="py-2 px-2 font-mono text-green-400">
                      ${p.profit_target?.toFixed(2)}
                    </td>
                    <td className="py-2 px-2 font-mono text-red-400">
                      ${p.stop_loss?.toFixed(2)}
                    </td>
                    <td className="py-2 px-2 text-xs text-slate-400">
                      {p.opened_at ? new Date(p.opened_at).toLocaleString() : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-slate-500 text-sm card">No open positions.</p>
        )}
      </div>

      {/* Closed trades */}
      <div>
        <h3 className="text-lg font-semibold mb-3 text-slate-400">
          Closed Trades ({closed?.length ?? 0})
        </h3>
        {closed && closed.length > 0 ? (
          <div className="overflow-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-slate-400 border-b border-slate-700">
                  <th className="py-2 px-2">Ticker</th>
                  <th className="py-2 px-2">Contract</th>
                  <th className="py-2 px-2">Type</th>
                  <th className="py-2 px-2">Qty</th>
                  <th className="py-2 px-2">Entry</th>
                  <th className="py-2 px-2">Exit</th>
                  <th className="py-2 px-2">P/L</th>
                  <th className="py-2 px-2">Exit Reason</th>
                  <th className="py-2 px-2">Closed</th>
                </tr>
              </thead>
              <tbody>
                {closed.map((p) => (
                  <tr key={p.id} className="border-b border-slate-800">
                    <td className="py-2 px-2 font-mono font-bold">{p.ticker}</td>
                    <td className="py-2 px-2 font-mono text-xs">
                      {p.contract_symbol}
                    </td>
                    <td className="py-2 px-2">
                      <span
                        className={`badge ${
                          p.option_type === "call" ? "badge-bullish" : "badge-bearish"
                        }`}
                      >
                        {p.option_type}
                      </span>
                    </td>
                    <td className="py-2 px-2 font-mono">{p.quantity}</td>
                    <td className="py-2 px-2 font-mono">
                      ${p.entry_price?.toFixed(2)}
                    </td>
                    <td className="py-2 px-2 font-mono">
                      ${p.current_price?.toFixed(2)}
                    </td>
                    <td
                      className={`py-2 px-2 font-mono font-bold ${
                        (p.realized_pnl ?? 0) >= 0
                          ? "text-green-400"
                          : "text-red-400"
                      }`}
                    >
                      {fmt$(p.realized_pnl)}
                    </td>
                    <td className="py-2 px-2">
                      <span
                        className={`badge ${
                          p.exit_reason === "profit_target"
                            ? "badge-bullish"
                            : p.exit_reason === "stop_loss"
                            ? "badge-bearish"
                            : "badge-warning"
                        }`}
                      >
                        {p.exit_reason}
                      </span>
                    </td>
                    <td className="py-2 px-2 text-xs text-slate-400">
                      {p.closed_at ? new Date(p.closed_at).toLocaleString() : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-slate-500 text-sm card">No closed trades yet.</p>
        )}
      </div>
    </div>
  );
}

function Stat({
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
      <div className="text-xs text-slate-400">{label}</div>
      <div className={`text-lg font-mono font-bold ${color}`}>{value}</div>
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
