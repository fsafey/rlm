import { useState } from "react";
import { ChevronDown, ChevronRight, Terminal } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Iteration } from "@/lib/types";

interface TracePanelProps {
  iterations: Iteration[];
  isLive: boolean;
}

export function TracePanel({ iterations, isLive }: TracePanelProps) {
  const [expanded, setExpanded] = useState(true);

  if (iterations.length === 0) return null;

  return (
    <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] shadow-sm overflow-hidden">
      {/* Header toggle */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-5 py-3 border-b border-[hsl(var(--border))] bg-[hsl(var(--muted))] hover:bg-[hsl(var(--accent))] transition-colors text-sm font-medium text-left"
      >
        <div className="flex items-center gap-2">
          <Terminal className="h-4 w-4" />
          Execution Trace
          <span className="text-xs text-[hsl(var(--muted-foreground))]">
            ({iterations.length} iteration{iterations.length !== 1 ? "s" : ""})
          </span>
          {isLive && (
            <span className="flex items-center gap-1 text-xs text-emerald-600">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
              Live
            </span>
          )}
        </div>
        {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
      </button>

      {expanded && (
        <div className="divide-y divide-[hsl(var(--border))]">
          {iterations.map((iter) => (
            <IterationRow key={iter.iteration} iteration={iter} />
          ))}
        </div>
      )}
    </div>
  );
}

function IterationRow({ iteration }: { iteration: Iteration }) {
  const [open, setOpen] = useState(false);
  const hasCode = iteration.code_blocks.length > 0;
  const hasError = iteration.code_blocks.some((b) => b.result?.stderr);

  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-5 py-3 hover:bg-[hsl(var(--accent))] transition-colors text-left"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 flex-shrink-0" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 flex-shrink-0" />
        )}
        <span className="text-xs font-mono text-[hsl(var(--muted-foreground))] w-6">
          #{iteration.iteration}
        </span>
        <span className="flex-1 text-sm truncate">
          {iteration.response.slice(0, 120)}
          {iteration.response.length > 120 ? "..." : ""}
        </span>
        <div className="flex items-center gap-2 flex-shrink-0">
          {hasCode && (
            <span
              className={cn(
                "text-[10px] rounded-full px-2 py-0.5",
                hasError
                  ? "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
                  : "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"
              )}
            >
              {iteration.code_blocks.length} block{iteration.code_blocks.length !== 1 ? "s" : ""}
            </span>
          )}
          {iteration.iteration_time !== null && (
            <span className="text-[10px] text-[hsl(var(--muted-foreground))]">
              {iteration.iteration_time.toFixed(1)}s
            </span>
          )}
        </div>
      </button>

      {open && (
        <div className="px-5 pb-4 space-y-3">
          {/* LM Response */}
          <div className="rounded-lg bg-[hsl(var(--muted))] p-3">
            <p className="text-[10px] uppercase tracking-wider text-[hsl(var(--muted-foreground))] mb-1.5 font-medium">
              LM Response
            </p>
            <pre className="text-xs whitespace-pre-wrap font-mono leading-relaxed max-h-64 overflow-y-auto">
              {iteration.response}
            </pre>
          </div>

          {/* Code blocks */}
          {iteration.code_blocks.map((block, idx) => (
            <div key={idx} className="space-y-2">
              <div className="rounded-lg bg-gray-900 text-gray-100 p-3">
                <p className="text-[10px] uppercase tracking-wider text-gray-400 mb-1.5 font-medium">
                  Code Block #{idx + 1}
                </p>
                <pre className="text-xs whitespace-pre-wrap font-mono leading-relaxed max-h-48 overflow-y-auto">
                  {block.code}
                </pre>
              </div>

              {block.result?.stdout && (
                <div className="rounded-lg bg-emerald-50 dark:bg-emerald-900/20 p-3">
                  <p className="text-[10px] uppercase tracking-wider text-emerald-600 dark:text-emerald-400 mb-1 font-medium">
                    stdout
                  </p>
                  <pre className="text-xs whitespace-pre-wrap font-mono text-emerald-700 dark:text-emerald-300 max-h-48 overflow-y-auto">
                    {block.result.stdout}
                  </pre>
                </div>
              )}

              {block.result?.stderr && (
                <div className="rounded-lg bg-red-50 dark:bg-red-900/20 p-3">
                  <p className="text-[10px] uppercase tracking-wider text-red-600 dark:text-red-400 mb-1 font-medium">
                    stderr
                  </p>
                  <pre className="text-xs whitespace-pre-wrap font-mono text-red-700 dark:text-red-300 max-h-48 overflow-y-auto">
                    {block.result.stderr}
                  </pre>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
