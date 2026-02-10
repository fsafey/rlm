import { useCallback, useRef, useState } from "react";
import type { Iteration, MetadataEvent, SearchSettings, SearchState, SSEEvent } from "./types";
import { defaultSettings, initialSearchState } from "./types";

export function useSearch() {
  const [state, setState] = useState<SearchState>(initialSearchState);
  const abortRef = useRef<AbortController | null>(null);

  const search = useCallback(async (query: string, settings?: SearchSettings) => {
    // Abort any in-flight search
    abortRef.current?.abort();
    const abort = new AbortController();
    abortRef.current = abort;

    setState({
      ...initialSearchState,
      status: "searching",
      query,
    });

    try {
      // Start search
      const res = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, settings: settings ?? defaultSettings }),
        signal: abort.signal,
      });

      if (!res.ok) {
        throw new Error(`Search failed: ${res.status}`);
      }

      const { search_id } = (await res.json()) as { search_id: string };
      console.log("[SEARCH] started:", search_id);

      setState((s) => ({ ...s, searchId: search_id }));

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

              case "done":
                console.log("[SSE] done | answer_len:", event.answer?.length, "time:", event.execution_time);
                setState((s) => ({
                  ...s,
                  status: "done",
                  answer: event.answer,
                  sources: event.sources,
                  executionTime: event.execution_time,
                  usage: event.usage,
                }));
                return;

              case "error":
                console.error("[SSE] error:", event.message);
                setState((s) => ({
                  ...s,
                  status: "error",
                  error: event.message,
                }));
                return;

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
    abortRef.current?.abort();
    setState(initialSearchState);
  }, []);

  return { state, search, reset };
}
