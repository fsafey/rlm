import { useState } from "react";
import { AlertCircle, ChevronDown, ChevronRight, Clock, MessageSquare } from "lucide-react";
import { AnswerPanel } from "./AnswerPanel";
import { SourceCards } from "./SourceCards";
import { TracePanel } from "./TracePanel";
import type { ConversationTurn } from "@/lib/types";

interface ConversationHistoryProps {
  turns: ConversationTurn[];
}

function TurnCard({ turn, index }: { turn: ConversationTurn; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const isError = turn.status === "error";

  return (
    <div className={`rounded-lg border overflow-hidden ${
      isError
        ? "border-red-200 dark:border-red-900/50 bg-red-50/30 dark:bg-red-900/10"
        : "border-border bg-card"
    }`}>
      {/* Collapsed header */}
      <button
        onClick={() => setExpanded((e) => !e)}
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-muted/50 transition-colors"
      >
        <span className="flex items-center justify-center w-5 h-5 rounded-full bg-muted text-[10px] font-medium text-muted-foreground flex-shrink-0">
          {index + 1}
        </span>
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />
        )}
        <span className="text-sm font-medium truncate flex-1">{turn.query}</span>
        <div className="flex items-center gap-2 flex-shrink-0">
          {isError && (
            <span className="flex items-center gap-0.5 text-[10px] text-red-600 dark:text-red-400 font-medium">
              <AlertCircle className="h-2.5 w-2.5" />
              Error
            </span>
          )}
          {turn.sources.length > 0 && (
            <span className="text-[10px] text-muted-foreground">
              {turn.sources.length} source{turn.sources.length !== 1 ? "s" : ""}
            </span>
          )}
          {turn.executionTime !== null && (
            <span className="flex items-center gap-0.5 text-[10px] text-muted-foreground">
              <Clock className="h-2.5 w-2.5" />
              {turn.executionTime.toFixed(1)}s
            </span>
          )}
        </div>
      </button>

      {/* Collapsed answer snippet */}
      {!expanded && turn.answer && (
        <div className="px-4 pb-3 -mt-1">
          <p className="text-xs text-muted-foreground line-clamp-2">
            {turn.answer.replace(/[#*_`>\[\]]/g, "").slice(0, 200)}
          </p>
        </div>
      )}

      {/* Expanded detail view */}
      {expanded && (
        <div className="border-t border-border space-y-4 p-4">
          {/* Error message */}
          {isError && turn.error && (
            <div className="rounded-lg border border-red-200 dark:border-red-900/50 bg-red-50 dark:bg-red-900/20 p-3 flex items-start gap-2">
              <AlertCircle className="h-4 w-4 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-xs font-medium text-red-800 dark:text-red-300">Search failed</p>
                <pre className="text-xs text-red-600 dark:text-red-400 mt-1 whitespace-pre-wrap font-mono">
                  {turn.error}
                </pre>
              </div>
            </div>
          )}

          {/* Answer */}
          {turn.answer && (
            <AnswerPanel
              answer={turn.answer}
              sources={turn.sources}
              executionTime={turn.executionTime}
            />
          )}

          {/* Sources */}
          {turn.sources.length > 0 && <SourceCards sources={turn.sources} />}

          {/* Trace */}
          {turn.iterations.length > 0 && (
            <TracePanel
              iterations={turn.iterations}
              metadata={turn.metadata}
              isLive={false}
            />
          )}
        </div>
      )}
    </div>
  );
}

export function ConversationHistory({ turns }: ConversationHistoryProps) {
  // Don't render the last turn — it's currently displayed as the main answer
  const previousTurns = turns.slice(0, -1);
  if (previousTurns.length === 0) return null;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <MessageSquare className="h-3.5 w-3.5" />
        <span>
          {previousTurns.length} previous{" "}
          {previousTurns.length === 1 ? "question" : "questions"} in this session
        </span>
      </div>
      <div className="space-y-1.5">
        {previousTurns.map((turn, i) => (
          <TurnCard key={turn.searchId || `error-${i}`} turn={turn} index={i} />
        ))}
      </div>
    </div>
  );
}
