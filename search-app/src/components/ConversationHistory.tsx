import { useState } from "react";
import Markdown from "react-markdown";
import { ChevronDown, ChevronRight, Clock, MessageSquare } from "lucide-react";
import type { ConversationTurn } from "@/lib/types";

interface ConversationHistoryProps {
  turns: ConversationTurn[];
}

function TurnCard({ turn, index }: { turn: ConversationTurn; index: number }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
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

      {expanded && turn.answer && (
        <div className="border-t border-border px-4 py-3">
          <div className="prose prose-sm max-w-none dark:prose-invert prose-p:leading-relaxed text-sm">
            <Markdown>{turn.answer}</Markdown>
          </div>
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
          <TurnCard key={turn.searchId} turn={turn} index={i} />
        ))}
      </div>
    </div>
  );
}
