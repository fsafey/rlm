import { useState, useEffect, useRef, useMemo } from "react";
import {
  Loader2,
  CheckCircle2,
  Search,
  BookOpen,
  Brain,
  ChevronDown,
  FileText,
  MessageSquare,
  Sparkles,
  Wrench,
} from "lucide-react";
import type { Iteration, MetadataEvent, ProgressEvent } from "@/lib/types";

interface SearchProgressProps {
  query: string;
  iterations: Iteration[];
  metadata: MetadataEvent | null;
  progressSteps: ProgressEvent[];
}

// --- Progress phase rendering ---

const PHASE_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  reasoning: Brain,
  tools: Wrench,
};

// --- Iteration activity detection ---

interface IterationActivity {
  label: string;
  metric: string;
  icon: React.ComponentType<{ className?: string }>;
}

function extractMetric(stdout: string, pattern: RegExp): string | null {
  const match = stdout.match(pattern);
  return match ? match[1] : null;
}

function detectActivity(iteration: Iteration): IterationActivity {
  const code = iteration.code_blocks.map((b) => b.code).join("\n");
  const stdout = iteration.code_blocks.map((b) => b.result.stdout).join("\n");

  if (code.includes("search(")) {
    const resultCount = extractMetric(stdout, /results=(\d+)/);
    const queryText = extractMetric(stdout, /query='([^']*?)'/);
    const truncated =
      queryText && queryText.length > 35
        ? `${queryText.slice(0, 35)}...`
        : queryText;
    const metric = resultCount
      ? `${resultCount} results${truncated ? ` for "${truncated}"` : ""}`
      : "Queried collections";
    return { label: "Search", metric, icon: Search };
  }

  if (code.includes("fiqh_lookup(")) {
    const bridgeCount = extractMetric(stdout, /bridges=(\d+)/);
    const queryText = extractMetric(stdout, /query='([^']*?)'/);
    const metric = bridgeCount
      ? `${bridgeCount} term bridges${queryText ? ` for "${queryText.slice(0, 30)}"` : ""}`
      : "Looked up terminology";
    return { label: "Terminology", metric, icon: BookOpen };
  }

  if (code.includes("format_evidence(")) {
    return {
      label: "Citations",
      metric: "Built source citations",
      icon: FileText,
    };
  }

  if (code.includes("FINAL_VAR(") || iteration.final_answer) {
    return {
      label: "Answer",
      metric: "Synthesized final answer",
      icon: MessageSquare,
    };
  }

  const blockCount = iteration.code_blocks.length;
  return {
    label: "Analyze",
    metric: `${blockCount} code block${blockCount !== 1 ? "s" : ""} executed`,
    icon: Sparkles,
  };
}

// --- Contextual active step based on what just happened ---

function getActiveText(
  activities: IterationActivity[],
  iterCount: number,
  maxIterations: number,
): { label: string; detail: string } {
  if (iterCount === 0) {
    return { label: "Connecting", detail: "Setting up search agent..." };
  }

  const last = activities[activities.length - 1];

  // Late stage — converging on an answer
  if (iterCount / maxIterations > 0.6) {
    return { label: "Converging", detail: "Refining final answer..." };
  }

  switch (last.label) {
    case "Search":
      return { label: "Reviewing", detail: "Analyzing search results..." };
    case "Terminology":
      return { label: "Applying", detail: "Incorporating terminology..." };
    case "Citations":
      return { label: "Composing", detail: "Preparing final response..." };
    case "Analyze":
      return { label: "Reasoning", detail: "Deepening analysis..." };
    default:
      return { label: "Thinking", detail: "Processing..." };
  }
}

// Max completed iteration rows visible before collapsing older ones
const MAX_VISIBLE = 4;

// --- Completed step row ---

function CompletedStep({
  icon: Icon,
  label,
  detail,
  duration,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  detail?: string;
  duration?: string;
}) {
  return (
    <div className="flex items-start gap-3">
      <div className="flex-shrink-0 mt-0.5">
        <CheckCircle2 className="w-5 h-5 text-emerald-500" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <Icon className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-sm font-medium text-foreground">{label}</span>
          {duration && (
            <span className="text-xs text-muted-foreground">{duration}</span>
          )}
        </div>
        {detail && (
          <p className="text-xs text-muted-foreground mt-0.5 truncate">
            {detail}
          </p>
        )}
      </div>
      <div className="flex-shrink-0 w-16 mt-1.5">
        <div className="h-1.5 bg-muted rounded-full overflow-hidden">
          <div className="h-full bg-emerald-500 w-full rounded-full" />
        </div>
      </div>
    </div>
  );
}

// --- Active step row ---

function ActiveStep({ label, detail }: { label: string; detail: string }) {
  return (
    <div className="flex items-start gap-3">
      <div className="flex-shrink-0 mt-0.5">
        <Loader2 className="w-5 h-5 text-primary animate-spin" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-primary">{label}</span>
          <span className="text-xs text-primary/70">{detail}</span>
        </div>
      </div>
      <div className="flex-shrink-0 w-16 mt-1.5">
        <div className="h-1.5 bg-muted rounded-full overflow-hidden">
          <div className="h-full bg-primary/50 w-1/2 animate-pulse rounded-full" />
        </div>
      </div>
    </div>
  );
}

// --- Collapsed summary row ---

function CollapsedSummary({
  count,
  expanded,
  onToggle,
}: {
  count: number;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      onClick={onToggle}
      className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors py-1 w-full"
    >
      <ChevronDown
        className={`w-3.5 h-3.5 transition-transform ${expanded ? "rotate-180" : ""}`}
      />
      <span>
        {expanded ? "Collapse" : `${count} earlier step${count !== 1 ? "s" : ""}`}
      </span>
      <div className="flex-1 border-t border-border/50" />
    </button>
  );
}

// --- Main component ---

export function SearchProgress({
  query,
  iterations,
  metadata,
  progressSteps,
}: SearchProgressProps) {
  const [elapsedMs, setElapsedMs] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const startTimeRef = useRef(Date.now());

  useEffect(() => {
    startTimeRef.current = Date.now();
    const interval = setInterval(() => {
      setElapsedMs(Date.now() - startTimeRef.current);
    }, 100);
    return () => clearInterval(interval);
  }, []);

  const activities = useMemo(
    () => iterations.map(detectActivity),
    [iterations],
  );

  const maxIterations = metadata?.max_iterations ?? 15;
  const hasIterations = iterations.length > 0;

  // Progress steps: during init they animate in; once iterations flow, all are "completed"
  const lastProgress = progressSteps[progressSteps.length - 1];
  const completedProgress = hasIterations
    ? progressSteps
    : progressSteps.slice(0, -1);
  const activeProgress = hasIterations ? null : lastProgress;

  // Collapsing: init steps + old iterations collapse when list gets long
  const allCompleted = [
    ...completedProgress.map((step) => ({
      kind: "progress" as const,
      step,
    })),
    ...activities.map((activity, idx) => ({
      kind: "iteration" as const,
      activity,
      iteration: iterations[idx],
    })),
  ];

  const needsCollapse = allCompleted.length > MAX_VISIBLE;
  const hiddenCount = needsCollapse ? allCompleted.length - MAX_VISIBLE : 0;
  const visibleCompleted =
    needsCollapse && !expanded
      ? allCompleted.slice(-MAX_VISIBLE)
      : allCompleted;

  // Contextual active step
  const activeText = activeProgress
    ? {
        label: activeProgress.detail,
        detail:
          activeProgress.phase === "reasoning"
            ? "This may take a moment..."
            : "",
      }
    : getActiveText(activities, iterations.length, maxIterations);

  return (
    <div className="w-full max-w-2xl mx-auto">
      <div className="rounded-xl border border-border bg-card overflow-hidden shadow-sm">
        {/* Header */}
        <div className="px-6 py-4 border-b border-border">
          <h2 className="text-sm font-semibold text-foreground tracking-tight">
            Researching Your Question
          </h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Searching sources and analyzing findings
          </p>
        </div>

        {/* Query preview */}
        <div className="px-6 py-3 bg-muted/50 border-b border-border">
          <p className="text-sm text-muted-foreground italic truncate">
            &ldquo;{query}&rdquo;
          </p>
        </div>

        {/* Steps timeline */}
        <div className="p-6 space-y-3">
          {/* Collapsed older steps */}
          {needsCollapse && hiddenCount > 0 && (
            <CollapsedSummary
              count={hiddenCount}
              expanded={expanded}
              onToggle={() => setExpanded((v) => !v)}
            />
          )}

          {/* Visible completed steps */}
          {visibleCompleted.map((item, idx) => {
            if (item.kind === "progress") {
              const Icon = PHASE_ICON[item.step.phase] ?? Sparkles;
              return (
                <CompletedStep
                  key={`p-${idx}`}
                  icon={Icon}
                  label={item.step.detail}
                />
              );
            }
            return (
              <CompletedStep
                key={`i-${idx}`}
                icon={item.activity.icon}
                label={item.activity.label}
                detail={item.activity.metric}
                duration={
                  item.iteration.iteration_time != null
                    ? `${item.iteration.iteration_time.toFixed(1)}s`
                    : undefined
                }
              />
            );
          })}

          {/* Active step */}
          <ActiveStep label={activeText.label} detail={activeText.detail} />
        </div>

        {/* Footer stats */}
        <div className="px-6 py-3 bg-muted/50 border-t border-border flex justify-between text-xs text-muted-foreground">
          <span>
            {iterations.length}/{maxIterations} iterations
          </span>
          <span>{(elapsedMs / 1000).toFixed(1)}s elapsed</span>
        </div>
      </div>
    </div>
  );
}
