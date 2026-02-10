import { useCallback } from "react";
import { useSearch } from "@/lib/useSearch";
import { SearchInput } from "@/components/SearchInput";
import { SearchProgress } from "@/components/SearchProgress";
import { AnswerPanel } from "@/components/AnswerPanel";
import { SourceCards } from "@/components/SourceCards";
import { TracePanel } from "@/components/TracePanel";
import { AlertCircle } from "lucide-react";
import type { SearchSettings } from "@/lib/types";

function App() {
  const { state, search, reset } = useSearch();

  const handleSearch = useCallback(
    (query: string, settings: SearchSettings) => {
      search(query, settings);
    },
    [search],
  );

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
          <span className="text-[10px] font-mono text-muted-foreground bg-muted px-2 py-1 rounded">
            v0.1.0
          </span>
        </div>
      </header>

      {/* Main content */}
      <main className="max-w-5xl mx-auto px-4 py-8 space-y-6">
        {/* Search bar */}
        <SearchInput
          onSearch={handleSearch}
          onReset={reset}
          isSearching={state.status === "searching"}
        />

        {/* Progress indicator */}
        {state.status === "searching" && (
          <div className="flex justify-center">
            <SearchProgress iterations={state.iterations} />
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
          <AnswerPanel
            answer={state.answer}
            sources={state.sources}
            executionTime={state.executionTime}
          />
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
