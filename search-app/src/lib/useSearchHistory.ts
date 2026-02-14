import { useCallback, useEffect, useState } from "react";
import type { Iteration, MetadataEvent, SearchSource } from "./types";
import { initialSearchState } from "./types";
import type { SearchAction } from "./searchReducer";

export interface LogEntry {
  filename: string;
  search_id: string;
  query: string;
  timestamp: string;
  root_model: string;
}

export function useSearchHistory(
  dispatch: React.Dispatch<SearchAction>,
  currentSearchId: string | null,
) {
  const [recentLogs, setRecentLogs] = useState<LogEntry[]>([]);
  const [loadingLog, setLoadingLog] = useState(false);

  useEffect(() => {
    fetch("/api/logs/recent?limit=10")
      .then((r) => (r.ok ? r.json() : []))
      .then(setRecentLogs)
      .catch(() => setRecentLogs([]));
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const logId = params.get("log");
    if (logId) {
      loadLog(logId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadLog = useCallback(
    async (searchId: string) => {
      setLoadingLog(true);
      try {
        const res = await fetch(`/api/logs/${searchId}`);
        if (!res.ok) throw new Error("Log not found");
        const data = await res.json();

        const metadata = data.metadata as MetadataEvent | null;
        const iterations = (data.iterations ?? []) as Iteration[];
        const done = data.done as {
          answer: string;
          sources: SearchSource[];
          execution_time: number;
          usage: Record<string, unknown>;
        } | null;
        const error = data.error as { message: string } | null;

        dispatch({
          type: "LOAD_LOG",
          payload: {
            status: done ? "done" : error ? "error" : "idle",
            query: metadata?.query ?? "",
            searchId: metadata?.search_id ?? searchId,
            metadata: metadata ?? null,
            iterations,
            answer: done?.answer ?? null,
            sources: done?.sources ?? [],
            executionTime: done?.execution_time ?? null,
            usage: done?.usage ?? null,
            error: error?.message ?? null,
          },
        });

        const url = new URL(window.location.href);
        url.searchParams.set("log", searchId);
        window.history.replaceState({}, "", url.toString());
      } catch {
        console.error("[HISTORY] failed to load log:", searchId);
      } finally {
        setLoadingLog(false);
      }
    },
    [dispatch],
  );

  const deleteLog = useCallback(
    async (searchId: string) => {
      setRecentLogs((prev) => prev.filter((l) => l.search_id !== searchId));

      const url = new URL(window.location.href);
      if (url.searchParams.get("log") === searchId) {
        url.searchParams.delete("log");
        window.history.replaceState({}, "", url.toString());
      }

      if (currentSearchId === searchId) {
        dispatch({ type: "LOAD_LOG", payload: { ...initialSearchState } });
      }

      try {
        const res = await fetch(`/api/logs/${searchId}`, { method: "DELETE" });
        if (!res.ok) throw new Error("Delete failed");
      } catch {
        fetch("/api/logs/recent?limit=10")
          .then((r) => (r.ok ? r.json() : []))
          .then(setRecentLogs)
          .catch(() => {});
      }
    },
    [dispatch, currentSearchId],
  );

  return { recentLogs, loadLog, deleteLog, loadingLog };
}
