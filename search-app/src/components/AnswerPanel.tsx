import { useState, useMemo } from "react";
import Markdown from "react-markdown";
import { parseCitations } from "@/lib/parseCitations";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { SearchSource } from "@/lib/types";
import { BookOpen, ChevronDown, ChevronRight, Clock } from "lucide-react";

interface AnswerPanelProps {
  answer: string;
  sources: SearchSource[];
  executionTime: number | null;
}

export function AnswerPanel({ answer, executionTime }: AnswerPanelProps) {
  const [expanded, setExpanded] = useState(true);
  const citations = useMemo(() => parseCitations(answer), [answer]);

  return (
    <Collapsible open={expanded} onOpenChange={setExpanded}>
      <div className="rounded-xl border border-border bg-card shadow-sm overflow-hidden">
        {/* Header toggle */}
        <CollapsibleTrigger asChild>
          <button className="w-full flex items-center justify-between px-5 py-3 border-b border-border bg-muted hover:bg-accent transition-colors text-sm font-medium text-left">
            <div className="flex items-center gap-2">
              <BookOpen className="h-4 w-4" />
              Answer
              {citations.length > 0 && (
                <span className="text-xs text-muted-foreground">
                  ({citations.length} source{citations.length !== 1 ? "s" : ""} cited)
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              {executionTime !== null && (
                <span className="flex items-center gap-1 text-xs text-muted-foreground">
                  <Clock className="h-3 w-3" />
                  {executionTime.toFixed(1)}s
                </span>
              )}
              {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            </div>
          </button>
        </CollapsibleTrigger>

        <CollapsibleContent>
          {/* Markdown body */}
          <div className="p-5 prose prose-sm max-w-none dark:prose-invert prose-headings:text-base prose-headings:font-semibold prose-p:leading-relaxed">
            <Markdown>{answer}</Markdown>
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}
