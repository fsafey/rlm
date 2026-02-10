import { useState, useEffect } from "react";
import { Terminal, ChevronDown, ChevronRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { IterationTimeline } from "./IterationTimeline";
import { ExecutionPanel } from "./ExecutionPanel";
import type { Iteration, MetadataEvent } from "@/lib/types";

interface TracePanelProps {
  iterations: Iteration[];
  metadata: MetadataEvent | null;
  isLive: boolean;
}

export function TracePanel({ iterations, metadata, isLive }: TracePanelProps) {
  const [expanded, setExpanded] = useState(true);
  const [selectedIteration, setSelectedIteration] = useState(0);

  // Auto-select latest iteration when live
  useEffect(() => {
    if (isLive && iterations.length > 0) {
      setSelectedIteration(iterations.length - 1);
    }
  }, [isLive, iterations.length]);

  if (iterations.length === 0) return null;

  const currentIteration = iterations[selectedIteration] ?? null;

  return (
    <Collapsible open={expanded} onOpenChange={setExpanded}>
      <div className="rounded-xl border border-border bg-card shadow-sm overflow-hidden">
        {/* Header toggle */}
        <CollapsibleTrigger asChild>
          <button className="w-full flex items-center justify-between px-5 py-3 border-b border-border bg-muted hover:bg-accent transition-colors text-sm font-medium text-left">
            <div className="flex items-center gap-2">
              <Terminal className="h-4 w-4" />
              Execution Trace
              <span className="text-xs text-muted-foreground">
                ({iterations.length} iteration{iterations.length !== 1 ? "s" : ""})
              </span>
              {isLive && (
                <span className="flex items-center gap-1 text-xs text-emerald-600">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  Live
                </span>
              )}
              {metadata && (
                <div className="flex items-center gap-1.5 ml-auto mr-2">
                  <Badge variant="secondary" className="text-[10px] font-mono">
                    {metadata.root_model}
                  </Badge>
                  <Badge variant="secondary" className="text-[10px] font-mono">
                    max {metadata.max_iterations} iter
                  </Badge>
                </div>
              )}
            </div>
            {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          </button>
        </CollapsibleTrigger>

        <CollapsibleContent>
          {/* Timeline */}
          <IterationTimeline
            iterations={iterations}
            selectedIteration={selectedIteration}
            onSelectIteration={setSelectedIteration}
          />

          {/* Execution detail */}
          <div className="h-[500px]">
            <ExecutionPanel iteration={currentIteration} />
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}
