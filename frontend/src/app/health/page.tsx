"use client";

import { useApi } from "@/lib/hooks";
import { HealthInfo, MarketClockInfo } from "@/lib/api";

export default function HealthPage() {
  const { data: health } = useApi<HealthInfo>("/api/health", 10000);
  const { data: clock } = useApi<MarketClockInfo>("/api/market-clock", 10000);

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">System Health</h2>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* System status */}
        <div className="card">
          <h3 className="text-lg font-semibold mb-4">Pipeline Status</h3>
          <div className="space-y-3">
            <StatusRow
              label="System"
              value={health?.status ?? "unknown"}
              ok={health?.status === "running"}
            />
            <StatusRow
              label="News Items"
              value={String(health?.news_count ?? 0)}
              ok={(health?.news_count ?? 0) > 0}
            />
            <StatusRow
              label="Last News Poll"
              value={
                health?.last_news_at
                  ? new Date(health.last_news_at).toLocaleString()
                  : "Never"
              }
              ok={!!health?.last_news_at}
            />
            <StatusRow
              label="Last Event"
              value={
                health?.last_event_at
                  ? new Date(health.last_event_at).toLocaleString()
                  : "Never"
              }
              ok={!!health?.last_event_at}
            />
            <StatusRow
              label="Active Candidates"
              value={String(health?.active_candidates ?? 0)}
              ok={true}
            />
            <StatusRow
              label="Open Positions"
              value={String(health?.open_positions ?? 0)}
              ok={true}
            />
          </div>
        </div>

        {/* Market clock */}
        <div className="card">
          <h3 className="text-lg font-semibold mb-4">Market Clock</h3>
          <div className="space-y-3">
            <StatusRow
              label="Status"
              value={clock?.status ?? "unknown"}
              ok={clock?.status === "OPEN_TRADING"}
            />
            <StatusRow
              label="Market Open"
              value={clock?.is_market_open ? "Yes" : "No"}
              ok={clock?.is_market_open ?? false}
            />
            <StatusRow
              label="New Entries Allowed"
              value={clock?.can_enter_new ? "Yes" : "No"}
              ok={clock?.can_enter_new ?? false}
            />
            <StatusRow
              label="After Cutoff (3:00 PM)"
              value={clock?.is_after_cutoff ? "Yes" : "No"}
              ok={!(clock?.is_after_cutoff ?? false)}
            />
            <StatusRow
              label="Current ET"
              value={
                clock?.current_et
                  ? new Date(clock.current_et).toLocaleString("en-US", {
                      timeZone: "America/New_York",
                    })
                  : "..."
              }
              ok={true}
            />
          </div>
        </div>
      </div>

      {/* Module health details */}
      <div className="card">
        <h3 className="text-lg font-semibold mb-4">Module Configuration</h3>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
          <ConfigItem label="News Poll Interval" value="180s" />
          <ConfigItem label="Decision Tick" value="30min" />
          <ConfigItem label="Options Refresh" value="30min" />
          <ConfigItem label="Market Open" value="09:30 ET" />
          <ConfigItem label="Last Entry" value="15:00 ET" />
          <ConfigItem label="Market Close" value="16:00 ET" />
          <ConfigItem label="Min Sentiment" value="|0.65|" />
          <ConfigItem label="Min Confidence" value="0.75" />
          <ConfigItem label="Min Coverage" value="3" />
          <ConfigItem label="Max Candidates" value="5/cycle" />
          <ConfigItem label="Max Positions" value="6" />
          <ConfigItem label="Risk Per Trade" value="1%" />
          <ConfigItem label="Profit Target" value="+30%" />
          <ConfigItem label="Stop Loss" value="-25%" />
          <ConfigItem label="Time Stop" value="6h" />
          <ConfigItem label="Starting Cash" value="$100,000" />
          <ConfigItem label="Delta Target" value="0.45-0.65" />
          <ConfigItem label="Strike Window" value="+-10" />
        </div>
      </div>
    </div>
  );
}

function StatusRow({
  label,
  value,
  ok,
}: {
  label: string;
  value: string;
  ok: boolean;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm text-slate-400">{label}</span>
      <div className="flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full ${ok ? "bg-green-400" : "bg-red-400"}`} />
        <span className="text-sm font-mono">{value}</span>
      </div>
    </div>
  );
}

function ConfigItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-slate-900 rounded px-3 py-2">
      <div className="text-xs text-slate-400">{label}</div>
      <div className="font-mono text-sm">{value}</div>
    </div>
  );
}
