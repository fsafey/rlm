import { useCallback, useRef, useState } from "react";
import type { Iteration, MetadataEvent, ProgressEvent, SearchSettings, SearchState, SSEEvent } from "./types";
import { defaultSettings, initialSearchState } from "./types";

export function useSearch() {
  const [state, setState] = useState<SearchState>(initialSearchState);
  const abortRef = useRef<AbortController | null>(null);
  const searchIdRef = useRef<string | null>(null);
  const sessionIdRef = useRef<string | null>(null);

  const search = useCallback(async (query: string, settings?: SearchSettings) => {
    // Abort any in-flight search
    abortRef.current?.abort();
    const abort = new AbortController();
    abortRef.current = abort;

    // Preserve session context for follow-ups
    setState((prev) => ({
      ...initialSearchState,
      status: "searching",
      query,
      sessionId: prev.sessionId,
      conversationHistory: prev.conversationHistory,
    }));

    try {
      // Start search — pass session_id for follow-ups
      const body: Record<string, unknown> = {
        query,
        settings: settings ?? defaultSettings,
      };
      if (sessionIdRef.current) {
        body.session_id = sessionIdRef.current;
      }

      const res = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: abort.signal,
      });

      if (!res.ok) {
        throw new Error(`Search failed: ${res.status}`);
      }

      const { search_id, session_id } = (await res.json()) as {
        search_id: string;
        session_id: string;
      };
      console.log("[SEARCH] started:", search_id, "session:", session_id);
      searchIdRef.current = search_id;
      sessionIdRef.current = session_id;

      setState((s) => ({ ...s, searchId: search_id, sessionId: session_id }));

      // Open SSE stream
      const stream = await fetch(`/api/search/${search_id}/stream`, {
        signal: abort.signal,
      });

      if (!stream.ok || !stream.body) {
        throw new Error("Failed to open event stream");
      }

      const reader = stream.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const json = line.slice(6).trim();
          if (!json) continue;

          try {
            const event = JSON.parse(json) as SSEEvent;

            switch (event.type) {
              case "iteration":
                console.log("[SSE] iteration", (event as Iteration).iteration, "| code_blocks:", (event as Iteration).code_blocks?.length ?? 0);
                setState((s) => ({
                  ...s,
                  iterations: [...s.iterations, event as Iteration],
                }));
                break;

              case "done": {
                console.log("[SSE] done | answer_len:", event.answer?.length, "time:", event.execution_time);
                setState((s) => ({
                  ...s,
                  status: "done",
                  answer: event.answer,
                  sources: event.sources,
                  executionTime: event.execution_time,
                  usage: event.usage,
                  conversationHistory: [
                    ...s.conversationHistory,
                    {
                      query: s.query,
                      answer: event.answer,
                      sources: event.sources,
                      searchId: s.searchId ?? "",
                      executionTime: event.execution_time,
                    },
                  ],
                }));
                return;
              }

              case "error":
                console.error("[SSE] error:", event.message);
                setState((s) => ({
                  ...s,
                  status: "error",
                  error: event.message,
                }));
                return;

              case "progress":
                console.log("[SSE] progress:", (event as ProgressEvent).phase, (event as ProgressEvent).detail);
                setState((s) => ({
                  ...s,
                  progressSteps: [...s.progressSteps, event as ProgressEvent],
                }));
                break;

              case "metadata":
                console.log("[SSE] metadata received", event);
                setState((s) => ({ ...s, metadata: event as MetadataEvent }));
                break;
            }
          } catch {
            console.warn("[SSE] malformed JSON:", json);
          }
        }
      }
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      console.error("[SEARCH] failed:", (err as Error).message);
      setState((s) => ({
        ...s,
        status: "error",
        error: (err as Error).message,
      }));
    }
  }, []);

  const reset = useCallback(() => {
    if (searchIdRef.current) {
      fetch(`/api/search/${searchIdRef.current}/cancel`, { method: "POST" }).catch(() => {});
      searchIdRef.current = null;
    }
    sessionIdRef.current = null;
    abortRef.current?.abort();
    setState(initialSearchState);
  }, []);

  const newSession = useCallback(() => {
    // Tear down persistent session on backend
    if (sessionIdRef.current) {
      fetch(`/api/session/${sessionIdRef.current}`, { method: "DELETE" }).catch(() => {});
      sessionIdRef.current = null;
    }
    if (searchIdRef.current) {
      fetch(`/api/search/${searchIdRef.current}/cancel`, { method: "POST" }).catch(() => {});
      searchIdRef.current = null;
    }
    abortRef.current?.abort();
    setState(initialSearchState);
  }, []);

  return { state, search, reset, newSession, setState };
}
