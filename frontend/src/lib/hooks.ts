"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createEventSocket, fetchApi, WSEvent } from "./api";

export function useApi<T>(path: string, interval = 10000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const result = await fetchApi<T>(path);
      setData(result);
      setError(null);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    load();
    const id = setInterval(load, interval);
    return () => clearInterval(id);
  }, [load, interval]);

  return { data, error, loading, reload: load };
}

export function useEventStream(maxEvents = 200) {
  const [events, setEvents] = useState<WSEvent[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const ws = createEventSocket(
      (evt) => {
        setEvents((prev) => [evt, ...prev].slice(0, maxEvents));
      },
      () => {
        // Reconnect after 3s
        setTimeout(() => {
          if (wsRef.current) {
            wsRef.current.close();
          }
          wsRef.current = createEventSocket(
            (evt) => setEvents((prev) => [evt, ...prev].slice(0, maxEvents))
          );
        }, 3000);
      }
    );
    wsRef.current = ws;
    return () => ws.close();
  }, [maxEvents]);

  return events;
}

export function useSignalNotifications() {
  const [permission, setPermission] = useState<NotificationPermission>("default");

  useEffect(() => {
    if (typeof window !== "undefined" && "Notification" in window) {
      setPermission(Notification.permission);
    }
  }, []);

  const requestPermission = useCallback(async () => {
    if (typeof window === "undefined" || !("Notification" in window)) return;
    const result = await Notification.requestPermission();
    setPermission(result);
  }, []);

  const notify = useCallback(
    (title: string, body: string, tag?: string) => {
      if (permission !== "granted") return;
      try {
        new Notification(title, {
          body,
          icon: "/favicon.ico",
          tag: tag || "signal",
          requireInteraction: true,
        });
      } catch {}
    },
    [permission]
  );

  return { permission, requestPermission, notify };
}

export function useSignalStream() {
  const events = useEventStream(100);
  const { notify } = useSignalNotifications();
  const lastNotified = useRef<string>("");

  useEffect(() => {
    if (events.length === 0) return;
    const latest = events[0];
    if (
      (latest.event_type === "SIGNAL_ALERT" || latest.event_type === "WATCH_ALERT") &&
      latest.ts !== lastNotified.current
    ) {
      lastNotified.current = latest.ts;
      const p = latest.payload || {};
      const ticker = p.ticker || latest.ticker || "???";
      const dir = p.direction || "";
      const action = p.action || (dir === "bullish" ? "CALL" : dir === "bearish" ? "PUT" : "");

      if (latest.event_type === "SIGNAL_ALERT") {
        const contract = p.suggested_contract;
        const contractInfo = contract
          ? `\n${contract.type?.toUpperCase()} $${contract.strike} ${contract.expiry} (score ${contract.score?.toFixed(0)})`
          : "";
        notify(
          `Signal: ${ticker} ${action}`,
          `Urgency: ${p.urgency?.toFixed(0) || "?"}${p.cross_tier_confirmed ? " [CROSS-CONFIRMED]" : ""}${contractInfo}`,
          `signal-${ticker}-${latest.ts}`
        );
      } else {
        notify(
          `Watch: ${ticker} ${action}`,
          p.message || `${dir} sentiment — watch at market open`,
          `watch-${ticker}-${latest.ts}`
        );
      }
    }
  }, [events, notify]);

  return events;
}
