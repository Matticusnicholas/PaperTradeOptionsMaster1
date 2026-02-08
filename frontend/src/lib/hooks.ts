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
