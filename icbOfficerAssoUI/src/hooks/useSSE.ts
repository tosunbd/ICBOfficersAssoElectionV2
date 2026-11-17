"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { DashboardData } from "@/lib/types";

interface UseSSEOptions {
  onUpdate?: (data: DashboardData) => void;
  onPaused?: () => void;
  onError?: (message: string) => void;
  reconnectDelay?: number;
  /** Change it to drop the connection and open a fresh one (e.g. when counting starts again). */
  resyncKey?: number;
}

/**
 * Subscribes to the live results stream of an election.
 * Tries the stream URLs in turn (see api.dashboard.streamUrls): one that
 * fails, or does not open within OPEN_TIMEOUT, hands over to the next, and the
 * one that worked is used again after a dropped connection.
 */
const OPEN_TIMEOUT = 6000;

export function useSSE(electionId: number | null, options: UseSSEOptions = {}) {
  const [isConnected, setIsConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const handlers = useRef(options);
  const resyncKey = options.resyncKey ?? 0;
  useEffect(() => {
    handlers.current = options;
  });

  useEffect(() => {
    if (!electionId) return;
    let source: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let openTimer: ReturnType<typeof setTimeout> | null = null;
    let closed = false;
    const urls = api.dashboard.streamUrls(electionId);
    let urlIndex = 0;
    let opened = false;

    // a URL that never opened is skipped at once; a working one that dropped is retried after a pause
    const fail = () => {
      if (openTimer) clearTimeout(openTimer);
      setIsConnected(false);
      source?.close();
      if (closed) return;
      const delay = opened ? handlers.current.reconnectDelay ?? 5000 : urlIndex + 1 < urls.length ? 0 : handlers.current.reconnectDelay ?? 5000;
      if (!opened) urlIndex = (urlIndex + 1) % urls.length;
      retry = setTimeout(connect, delay);
    };

    const connect = () => {
      opened = false;
      source = new EventSource(urls[urlIndex]);
      openTimer = setTimeout(fail, OPEN_TIMEOUT);
      source.onopen = () => {
        if (openTimer) clearTimeout(openTimer);
        opened = true;
        setIsConnected(true);
      };
      source.addEventListener("update", (event) => {
        try {
          handlers.current.onUpdate?.(JSON.parse((event as MessageEvent).data));
          setLastUpdate(new Date());
        } catch (error) {
          console.error("Bad SSE payload", error);
        }
      });
      source.addEventListener("paused", () => handlers.current.onPaused?.());
      source.addEventListener("error", (event) => {
        const data = (event as MessageEvent).data;
        if (typeof data === "string") {
          try {
            handlers.current.onError?.(JSON.parse(data).error ?? "Unknown error");
          } catch {
            /* connection error, not a payload */
          }
        }
      });
      source.onerror = fail;
    };

    connect();
    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      if (openTimer) clearTimeout(openTimer);
      source?.close();
      setIsConnected(false);
    };
  }, [electionId, resyncKey]);

  return { isConnected, lastUpdate };
}
