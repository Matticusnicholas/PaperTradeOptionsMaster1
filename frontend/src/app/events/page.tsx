"use client";

import { useState } from "react";
import { useApi, useEventStream } from "@/lib/hooks";
import { WSEvent } from "@/lib/api";

export default function EventsPage() {
  const events = useEventStream(500);
  const [typeFilter, setTypeFilter] = useState("");
  const [tickerFilter, setTickerFilter] = useState("");
  const [severityFilter, setSeverityFilter] = useState("");

  const filtered = events.filter((e) => {
    if (typeFilter && !e.event_type.toLowerCase().includes(typeFilter.toLowerCase())) return false;
    if (tickerFilter && e.ticker?.toLowerCase() !== tickerFilter.toLowerCase()) return false;
    if (severityFilter && e.severity !== severityFilter) return false;
    return true;
  });

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-bold">Live Events Stream</h2>

      {/* Filters */}
      <div className="flex gap-3">
        <input
          className="bg-slate-800 border border-slate-600 rounded px-3 py-1.5 text-sm"
          placeholder="Filter by type..."
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
        />
        <input
          className="bg-slate-800 border border-slate-600 rounded px-3 py-1.5 text-sm"
          placeholder="Filter by ticker..."
          value={tickerFilter}
          onChange={(e) => setTickerFilter(e.target.value)}
        />
        <select
          className="bg-slate-800 border border-slate-600 rounded px-3 py-1.5 text-sm"
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value)}
        >
          <option value="">All severities</option>
          <option value="info">Info</option>
          <option value="warning">Warning</option>
          <option value="error">Error</option>
        </select>
        <span className="text-sm text-slate-400 self-center">
          {filtered.length} events
        </span>
      </div>

      {/* Event list */}
      <div className="space-y-1 max-h-[calc(100vh-200px)] overflow-auto">
        {filtered.length > 0 ? (
          filtered.map((e, i) => <EventRow key={i} event={e} />)
        ) : (
          <p className="text-slate-500 text-sm p-4">
            Waiting for events...
          </p>
        )}
      </div>
    </div>
  );
}

function EventRow({ event: e }: { event: WSEvent }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      className="bg-slate-800 border border-slate-700 rounded px-3 py-2 cursor-pointer hover:bg-slate-750"
      onClick={() => setExpanded(!expanded)}
    >
      <div className="flex items-center gap-2 text-sm">
        <span className="text-slate-500 font-mono text-xs whitespace-nowrap">
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
          <span className="font-mono text-blue-400 text-xs">{e.ticker}</span>
        )}
        <span className="text-slate-500 text-xs">{e.module}</span>
        <span className="text-slate-400 text-xs truncate flex-1">
          {summarize(e.payload)}
        </span>
      </div>
      {expanded && (
        <pre className="mt-2 text-xs text-slate-400 bg-slate-900 rounded p-2 overflow-auto max-h-48">
          {JSON.stringify(e.payload, null, 2)}
        </pre>
      )}
    </div>
  );
}

function summarize(payload: Record<string, any>): string {
  if (!payload) return "";
  if (payload.title) return payload.title;
  if (payload.message) return payload.message;
  if (payload.reason) return payload.reason;
  if (payload.ticker) return payload.ticker;
  const keys = Object.keys(payload).slice(0, 3);
  return keys.map((k) => `${k}=${JSON.stringify(payload[k])}`).join(" ");
}
