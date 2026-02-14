import { useCallback, useReducer, useRef } from "react";
import type {
  DoneEvent,
  ErrorEvent,
  Iteration,
  MetadataEvent,
  ProgressEvent,
  SearchSettings,
  SSEEvent,
  SubIterationEvent,
  ToolProgressEvent,
} from "./types";
import { defaultSettings, initialSearchState } from "./types";
import { searchReducer } from "./searchReducer";

export function useSearch() {
  const [state, dispatch] = useReducer(searchReducer, initialSearchState);
  const abortRef = useRef<AbortController | null>(null);
  const searchIdRef = useRef<string | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const cancellingRef = useRef(false);

  const search = useCallback(
    async (query: string, settings?: SearchSettings) => {
      if (cancellingRef.current) return;

      abortRef.current?.abort();
      const abort = new AbortController();
      abortRef.current = abort;

      dispatch({
        type: "SEARCH_START",
        query,
        sessionId: sessionIdRef.current,
        history: state.conversationHistory,
      });

      try {
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

        dispatch({ type: "SEARCH_CONNECTED", searchId: search_id, sessionId: session_id });

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
                  console.log(
                    "[SSE] iteration",
                    (event as Iteration).iteration,
                    "| code_blocks:",
                    (event as Iteration).code_blocks?.length ?? 0,
                  );
                  dispatch({ type: "SSE_ITERATION", event: event as Iteration });
                  break;

                case "sub_iteration":
                  console.log(
                    "[SSE] sub_iteration for:",
                    (event as SubIterationEvent).sub_question,
                  );
                  dispatch({ type: "SSE_SUB_ITERATION", event: event as SubIterationEvent });
                  break;

                case "tool_progress":
                  dispatch({ type: "SSE_TOOL_PROGRESS", event: event as ToolProgressEvent });
                  break;

                case "done":
                  console.log(
                    "[SSE] done | answer_len:",
                    (event as DoneEvent).answer?.length,
                    "time:",
                    (event as DoneEvent).execution_time,
                  );
                  dispatch({ type: "SSE_DONE", event: event as DoneEvent });
                  return;

                case "error":
                  console.error("[SSE] error:", (event as ErrorEvent).message);
                  dispatch({ type: "SSE_ERROR", event: event as ErrorEvent });
                  return;

                case "cancelled":
                  console.log("[SSE] cancelled by server");
                  dispatch({ type: "SSE_CANCELLED" });
                  return;

                case "progress":
                  console.log(
                    "[SSE] progress:",
                    (event as ProgressEvent).phase,
                    (event as ProgressEvent).detail,
                  );
                  dispatch({ type: "SSE_PROGRESS", event: event as ProgressEvent });
                  break;

                case "metadata":
                  console.log("[SSE] metadata received", event);
                  dispatch({ type: "SSE_METADATA", event: event as MetadataEvent });
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
        dispatch({
          type: "SSE_ERROR",
          event: { type: "error", message: (err as Error).message },
        });
      }
    },
    [state.conversationHistory],
  );

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;

    cancellingRef.current = true;
    dispatch({ type: "CANCEL_START" });

    if (searchIdRef.current) {
      fetch(`/api/search/${searchIdRef.current}/cancel`, { method: "POST" }).catch(() => {});
      searchIdRef.current = null;
    }

    setTimeout(() => {
      cancellingRef.current = false;
      dispatch({ type: "CANCEL_TIMEOUT" });
    }, 800);
  }, []);

  const newSession = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;

    if (searchIdRef.current) {
      fetch(`/api/search/${searchIdRef.current}/cancel`, { method: "POST" }).catch(() => {});
      searchIdRef.current = null;
    }

    if (sessionIdRef.current) {
      fetch(`/api/session/${sessionIdRef.current}`, { method: "DELETE" }).catch(() => {});
      sessionIdRef.current = null;
    }

    cancellingRef.current = false;
    dispatch({ type: "NEW_SESSION" });
  }, []);

  return { state, dispatch, search, reset, newSession };
}
