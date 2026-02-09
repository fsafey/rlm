import { useMemo } from "react";
import Markdown from "react-markdown";
import { parseCitations } from "@/lib/parseCitations";
import type { SearchSource } from "@/lib/types";
import { BookOpen, Clock } from "lucide-react";

interface AnswerPanelProps {
  answer: string;
  sources: SearchSource[];
  executionTime: number | null;
}

export function AnswerPanel({ answer, executionTime }: AnswerPanelProps) {
  const citations = useMemo(() => parseCitations(answer), [answer]);

  return (
    <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] shadow-sm overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-[hsl(var(--border))] bg-[hsl(var(--muted))]">
        <div className="flex items-center gap-2 text-sm font-medium">
          <BookOpen className="h-4 w-4" />
          Answer
          {citations.length > 0 && (
            <span className="text-xs text-[hsl(var(--muted-foreground))]">
              ({citations.length} source{citations.length !== 1 ? "s" : ""} cited)
            </span>
          )}
        </div>
        {executionTime !== null && (
          <div className="flex items-center gap-1 text-xs text-[hsl(var(--muted-foreground))]">
            <Clock className="h-3 w-3" />
            {executionTime.toFixed(1)}s
          </div>
        )}
      </div>

      {/* Markdown body */}
      <div className="p-5 prose prose-sm max-w-none dark:prose-invert prose-headings:text-base prose-headings:font-semibold prose-p:leading-relaxed">
        <Markdown>{answer}</Markdown>
      </div>
    </div>
  );
}
