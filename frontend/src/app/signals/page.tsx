"use client";

import { useApi } from "@/lib/hooks";
import { useSignalNotifications, useSignalStream } from "@/lib/hooks";
import { MarketClockInfo, SignalAlert } from "@/lib/api";

export default function SignalHub() {
  const { data: signals } = useApi<SignalAlert[]>("/api/signals?limit=50", 5000);
  const { data: clock } = useApi<MarketClockInfo>("/api/market-clock", 10000);
  const { permission, requestPermission } = useSignalNotifications();
  const liveEvents = useSignalStream();

  // Separate live signal/watch alerts from the WS stream
  const liveAlerts = liveEvents.filter(
    (e) => e.event_type === "SIGNAL_ALERT" || e.event_type === "WATCH_ALERT"
  );

  const clockColor =
    clock?.status === "OPEN_TRADING"
      ? "text-green-400"
      : clock?.status === "OPEN_NO_NEW_ENTRIES"
      ? "text-yellow-400"
      : "text-red-400";

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Signal Hub</h2>
        <div className="flex items-center gap-4">
          <span className={`font-mono text-sm ${clockColor}`}>
            {clock?.status ?? "..."}
          </span>
          {permission !== "granted" ? (
            <button
              onClick={requestPermission}
              className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-500 transition-colors"
            >
              Enable Notifications
            </button>
          ) : (
            <span className="text-xs text-green-400 bg-green-900/30 px-2 py-1 rounded">
              Notifications ON
            </span>
          )}
        </div>
      </div>

      {/* Notification permission banner */}
      {permission === "default" && (
        <div className="card border-blue-500/50 bg-blue-950/30">
          <div className="flex items-center justify-between">
            <div>
              <div className="font-semibold text-blue-400">
                Enable Push Notifications
              </div>
              <div className="text-sm text-slate-400 mt-1">
                Get instant browser alerts when new CALL/PUT signals or
                off-hours watch alerts are detected. The server processes
                everything — you just need the tab open.
              </div>
            </div>
            <button
              onClick={requestPermission}
              className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-500 ml-4 whitespace-nowrap"
            >
              Allow Notifications
            </button>
          </div>
        </div>
      )}

      {/* Live alerts from WebSocket */}
      {liveAlerts.length > 0 && (
        <div>
          <h3 className="text-lg font-semibold mb-3 text-yellow-400">
            Live Alerts
          </h3>
          <div className="space-y-2">
            {liveAlerts.slice(0, 10).map((e, i) => (
              <LiveAlertCard key={i} event={e} />
            ))}
          </div>
        </div>
      )}

      {/* Historical signals from API */}
      <div>
        <h3 className="text-lg font-semibold mb-3">Signal History</h3>
        {signals && signals.length > 0 ? (
          <div className="space-y-3">
            {signals.map((s) => (
              <SignalCard key={s.id} signal={s} />
            ))}
          </div>
        ) : (
          <div className="card text-slate-500 text-sm">
            No signals yet. The system will emit SIGNAL_ALERT events when
            confirmed candidates are detected during market hours, and
            WATCH_ALERT events for off-hours sentiment discoveries.
          </div>
        )}
      </div>
    </div>
  );
}

function LiveAlertCard({ event: e }: { event: any }) {
  const p = e.payload || {};
  const isSignal = e.event_type === "SIGNAL_ALERT";
  const borderColor = isSignal ? "border-yellow-500/50" : "border-purple-500/50";
  const bgColor = isSignal ? "bg-yellow-950/20" : "bg-purple-950/20";

  return (
    <div className={`card ${borderColor} ${bgColor} animate-pulse`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span
            className={`badge ${isSignal ? "badge-warning" : "badge-info"}`}
          >
            {e.event_type}
          </span>
          <span className="text-lg font-mono font-bold">
            {p.ticker || e.ticker}
          </span>
          <span
            className={`badge ${
              p.direction === "bullish" ? "badge-bullish" : "badge-bearish"
            }`}
          >
            {p.action || (p.direction === "bullish" ? "CALL" : "PUT")}
          </span>
          {p.cross_tier_confirmed && (
            <span className="badge bg-amber-900 text-amber-300">
              CROSS-CONFIRMED
            </span>
          )}
        </div>
        <span className="text-xs text-slate-500">
          {e.ts ? new Date(e.ts).toLocaleTimeString() : "now"}
        </span>
      </div>
      {p.suggested_contract && (
        <ContractSuggestion contract={p.suggested_contract} />
      )}
      {p.message && (
        <div className="text-sm text-slate-300 mt-1">{p.message}</div>
      )}
    </div>
  );
}

function SignalCard({ signal: s }: { signal: SignalAlert }) {
  const p = s.payload;
  const isSignal = s.event_type === "SIGNAL_ALERT";
  const borderColor = isSignal
    ? p.cross_tier_confirmed
      ? "border-amber-500/50"
      : "border-slate-600"
    : "border-purple-500/30";

  return (
    <div className={`card ${borderColor}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span
            className={`badge ${isSignal ? "badge-warning" : "badge-info"}`}
          >
            {s.event_type === "SIGNAL_ALERT" ? "SIGNAL" : "WATCH"}
          </span>
          <span className="text-lg font-mono font-bold">{s.ticker}</span>
          <span
            className={`badge ${
              p.direction === "bullish" ? "badge-bullish" : "badge-bearish"
            }`}
          >
            {p.action || (p.direction === "bullish" ? "CALL" : "PUT")}
          </span>
          {p.cross_tier_confirmed && (
            <span className="badge bg-amber-900 text-amber-300 text-xs">
              CROSS-TIER
            </span>
          )}
          {p.flow_confirmed && (
            <span className="badge bg-cyan-900 text-cyan-300 text-xs">
              FLOW
            </span>
          )}
        </div>
        <div className="text-right">
          <div className="text-sm text-slate-400">
            {s.ts ? new Date(s.ts).toLocaleString() : ""}
          </div>
          <div className="text-xs text-slate-500">{p.market_status}</div>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-3 text-sm mb-2">
        <div>
          <span className="text-slate-400">Urgency:</span>{" "}
          <span className="font-mono font-bold">{p.urgency?.toFixed(0)}</span>
        </div>
        {p.underlying_price && (
          <div>
            <span className="text-slate-400">Price:</span>{" "}
            <span className="font-mono">${p.underlying_price?.toFixed(2)}</span>
          </div>
        )}
        {p.flow_score != null && p.flow_score > 0 && (
          <div>
            <span className="text-slate-400">Flow:</span>{" "}
            <span className="font-mono">{p.flow_score?.toFixed(0)}</span>
          </div>
        )}
      </div>

      {p.suggested_contract && (
        <ContractSuggestion contract={p.suggested_contract} />
      )}

      {p.rationale && (
        <div className="text-xs text-slate-400 italic mt-2">
          {p.rationale}
        </div>
      )}
      {p.message && (
        <div className="text-sm text-slate-300 mt-2">{p.message}</div>
      )}
    </div>
  );
}

function ContractSuggestion({
  contract,
}: {
  contract: SignalAlert["payload"]["suggested_contract"];
}) {
  if (!contract) return null;
  return (
    <div className="bg-slate-900 rounded p-2 text-sm">
      <div className="flex items-center gap-3">
        <span className="text-slate-400">Suggested:</span>
        <span className="font-mono font-bold">{contract.symbol}</span>
        <span
          className={`badge text-xs ${
            contract.type === "call" ? "badge-bullish" : "badge-bearish"
          }`}
        >
          {contract.type?.toUpperCase()}
        </span>
        <span className="font-mono">${contract.strike}</span>
        <span className="text-slate-400">{contract.expiry}</span>
      </div>
      <div className="flex gap-4 mt-1 text-xs text-slate-400">
        <span>Score: <span className="font-mono text-white">{contract.score?.toFixed(0)}</span></span>
        <span>Delta: <span className="font-mono">{contract.delta?.toFixed(2)}</span></span>
        <span>IV: <span className="font-mono">{(contract.iv * 100)?.toFixed(0)}%</span></span>
        <span>Bid: <span className="font-mono">${contract.bid?.toFixed(2)}</span></span>
        <span>Ask: <span className="font-mono">${contract.ask?.toFixed(2)}</span></span>
      </div>
    </div>
  );
}
