import { useCallback, useEffect, useRef } from "react";
import { useSearch } from "@/lib/useSearch";
import { useSearchHistory } from "@/lib/useSearchHistory";
import { SearchInput } from "@/components/SearchInput";
import { SearchProgress } from "@/components/SearchProgress";
import { AnswerPanel } from "@/components/AnswerPanel";
import { SourceCards } from "@/components/SourceCards";
import { TracePanel } from "@/components/TracePanel";
import { RecentSearches } from "@/components/RecentSearches";
import { ConversationHistory } from "@/components/ConversationHistory";
import { AlertCircle, RotateCcw } from "lucide-react";
import type { SearchSettings, SearchState } from "@/lib/types";

function App() {
  const { state, search, reset, newSession, setState } = useSearch();
  const { recentLogs, loadLog, deleteLog, loadingLog } = useSearchHistory(
    setState as React.Dispatch<React.SetStateAction<SearchState>>,
  );

  const handleSearch = useCallback(
    (query: string, settings: SearchSettings) => {
      // Clear URL param when starting a new search
      const url = new URL(window.location.href);
      url.searchParams.delete("log");
      window.history.replaceState({}, "", url.toString());
      search(query, settings);
    },
    [search],
  );

  const handleReset = useCallback(() => {
    const url = new URL(window.location.href);
    url.searchParams.delete("log");
    window.history.replaceState({}, "", url.toString());
    reset();
  }, [reset]);

  const handleNewSession = useCallback(() => {
    const url = new URL(window.location.href);
    url.searchParams.delete("log");
    window.history.replaceState({}, "", url.toString());
    newSession();
  }, [newSession]);

  const answerRef = useRef<HTMLDivElement>(null);
  const prevStatusRef = useRef(state.status);

  // Scroll to answer when search completes or a log is loaded
  useEffect(() => {
    const prev = prevStatusRef.current;
    prevStatusRef.current = state.status;

    if (!state.answer) return;

    // Search just finished, or a log was loaded (idle/done with new answer)
    const justFinished = prev === "searching" && state.status !== "searching";
    const logLoaded = prev !== state.status && (state.status === "done" || state.status === "idle");

    if (justFinished || logLoaded) {
      const t = setTimeout(() => {
        answerRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 100);
      return () => clearTimeout(t);
    }
  }, [state.answer, state.status]);

  const isInSession = state.sessionId !== null && state.conversationHistory.length > 0;

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b border-border bg-card">
        <div className="max-w-5xl mx-auto px-4 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold">RLM Search</h1>
            <p className="text-xs text-muted-foreground">
              Agentic search over Islamic jurisprudence
            </p>
          </div>
          <div className="flex items-center gap-3">
            {(isInSession || state.status === "done" || state.status === "error") && (
              <button
                onClick={handleNewSession}
                className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground bg-muted hover:bg-muted/80 px-3 py-1.5 rounded-lg transition-colors"
                title="Clear results and start a fresh search session"
              >
                <RotateCcw className="h-3 w-3" />
                New Session
              </button>
            )}
            <span className="text-[10px] font-mono text-muted-foreground bg-muted px-2 py-1 rounded">
              v0.1.0
            </span>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="max-w-5xl mx-auto px-4 py-8 space-y-6">
        {/* Search bar */}
        <SearchInput
          onSearch={handleSearch}
          onReset={handleReset}
          isSearching={state.status === "searching" || state.status === "cancelling"}
          isCancelling={state.status === "cancelling"}
          isFollowUp={isInSession && state.status !== "searching"}
        />

        {/* Recent searches — shown when idle with no session */}
        {state.status === "idle" && !isInSession && (
          <RecentSearches
            logs={recentLogs}
            onSelect={loadLog}
            onDelete={deleteLog}
            loading={loadingLog}
          />
        )}

        {/* Conversation history — show previous turns */}
        {state.conversationHistory.length > 0 && (
          <ConversationHistory turns={state.conversationHistory} />
        )}

        {/* Progress indicator */}
        {state.status === "searching" && (
          <div className="flex justify-center">
            <SearchProgress
              query={state.query}
              iterations={state.iterations}
              metadata={state.metadata}
              progressSteps={state.progressSteps}
              toolProgress={state.toolProgress}
              subIterations={state.subIterations}
            />
          </div>
        )}

        {/* Cancelling indicator */}
        {state.status === "cancelling" && (
          <div className="flex justify-center">
            <div className="text-sm text-muted-foreground animate-pulse">
              Cancelling search...
            </div>
          </div>
        )}

        {/* Error state */}
        {state.status === "error" && state.error && (
          <div className="rounded-xl border border-red-200 dark:border-red-900/50 bg-red-50 dark:bg-red-900/20 p-4 flex items-start gap-3">
            <AlertCircle className="h-5 w-5 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-red-800 dark:text-red-300">Search failed</p>
              <pre className="text-xs text-red-600 dark:text-red-400 mt-1 whitespace-pre-wrap font-mono">
                {state.error}
              </pre>
            </div>
          </div>
        )}

        {/* Answer */}
        {state.answer && (
          <div ref={answerRef}>
          <AnswerPanel
            answer={state.answer}
            sources={state.sources}
            executionTime={state.executionTime}
          />
          </div>
        )}

        {/* Sources */}
        {state.sources.length > 0 && <SourceCards sources={state.sources} />}

        {/* Trace */}
        {state.iterations.length > 0 && (
          <TracePanel
            iterations={state.iterations}
            metadata={state.metadata}
            isLive={state.status === "searching"}
          />
        )}
      </main>
    </div>
  );
}

export default App;
