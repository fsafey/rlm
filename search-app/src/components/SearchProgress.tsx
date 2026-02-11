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
  RefreshCw,
  ShieldCheck,
  Tag,
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

/**
 * Detect iteration activity from stdout tags emitted by REPL tools.
 *
 * Each tool in repl_tools.py prints a structured `[tag] ...` line. We match
 * these tags (most-specific first) to classify what the iteration did. This
 * is more reliable than matching code strings because the stdout patterns are
 * hardcoded in the tool implementations and cover composite tools that wrap
 * multiple lower-level calls.
 */
function detectActivity(iteration: Iteration): IterationActivity {
  const stdout = iteration.code_blocks.map((b) => b.result.stdout).join("\n");

  // --- Final answer (check first — takes priority) ---
  if (iteration.final_answer) {
    return { label: "Answer", metric: "Synthesized final answer", icon: MessageSquare };
  }

  // --- Composite tools (check before their sub-tools) ---

  // draft_answer wraps format_evidence + synthesis + critique + optional revision
  if (stdout.includes("[draft_answer]")) {
    const passed = stdout.includes("PASS");
    const revised = stdout.includes("(revised)");
    let metric = passed ? "Drafted and verified" : "Drafted, needs revision";
    if (revised) metric = "Drafted, revised, and verified";
    return { label: "Drafting", metric, icon: MessageSquare };
  }

  // research wraps search + evaluate + dedup
  if (stdout.includes("[research]")) {
    const searchCount = extractMetric(stdout, /\[research\] (\d+) searches/);
    const summary = extractMetric(stdout, /\[research\] (.+? off-topic)/);
    const metric = summary
      ? `${searchCount ?? "?"} searches — ${summary}`
      : `${searchCount ?? "Multiple"} searches run`;
    return { label: "Researching", metric, icon: Search };
  }

  // --- Sub-agent tools ---

  if (stdout.includes("[evaluate_results]")) {
    const summary = extractMetric(stdout, /\[evaluate_results\] \d+ rated: (.+)/);
    return {
      label: "Evaluating",
      metric: summary ?? "Rated search results",
      icon: ShieldCheck,
    };
  }

  if (stdout.includes("[critique_answer]")) {
    const verdict = extractMetric(stdout, /\[critique_answer\] verdict=(\w+)/);
    return {
      label: "Critiquing",
      metric: verdict ? `Verdict: ${verdict}` : "Reviewed draft",
      icon: ShieldCheck,
    };
  }

  if (stdout.includes("[reformulate]")) {
    const count = extractMetric(stdout, /\[reformulate\] generated (\d+) queries/);
    return {
      label: "Reformulating",
      metric: count ? `${count} alternative queries` : "Generated alternatives",
      icon: RefreshCw,
    };
  }

  if (stdout.includes("[classify_question]")) {
    return { label: "Classifying", metric: "Identified category and strategy", icon: Tag };
  }

  // --- Primary tools ---

  if (stdout.includes("[search]")) {
    const resultCount = extractMetric(stdout, /\[search\] query=.+? results=(\d+)/);
    const queryText = extractMetric(stdout, /\[search\] query='([^']*?)'/);
    const truncated =
      queryText && queryText.length > 35 ? `${queryText.slice(0, 35)}...` : queryText;
    const metric = resultCount
      ? `${resultCount} results${truncated ? ` for "${truncated}"` : ""}`
      : "Queried knowledge base";
    return { label: "Searching", metric, icon: Search };
  }

  if (stdout.includes("[browse]")) {
    const total = extractMetric(stdout, /\[browse\] .+? total=(\d+)/);
    const metric = total ? `${total} documents browsed` : "Browsed knowledge base";
    return { label: "Browsing", metric, icon: Search };
  }

  if (stdout.includes("[fiqh_lookup]")) {
    const bridgeCount = extractMetric(stdout, /\[fiqh_lookup\] .+? bridges=(\d+)/);
    const queryText = extractMetric(stdout, /\[fiqh_lookup\] query='([^']*?)'/);
    const metric = bridgeCount
      ? `${bridgeCount} term bridges${queryText ? ` for "${queryText.slice(0, 30)}"` : ""}`
      : "Looked up terminology";
    return { label: "Terminology", metric, icon: BookOpen };
  }

  // --- KB overview (orientation step) ---
  if (stdout.includes("=== Knowledge Base:")) {
    return { label: "Exploring KB", metric: "Reviewing taxonomy and categories", icon: BookOpen };
  }

  // --- Fallback ---
  const blockCount = iteration.code_blocks.length;
  return {
    label: "Processing",
    metric: `${blockCount} code block${blockCount !== 1 ? "s" : ""} executed`,
    icon: Sparkles,
  };
}

// --- Contextual active step based on what just happened ---

function getActiveText(
  activities: IterationActivity[],
  _iterCount: number,
  _maxIterations: number,
): { label: string; detail: string } {
  if (activities.length === 0) {
    return { label: "Connecting", detail: "Setting up search agent..." };
  }

  const last = activities[activities.length - 1];

  // Predict the likely next step based on what just completed.
  // Matches the real tool pipeline in repl_tools.py.
  switch (last.label) {
    case "Exploring KB":
      return { label: "Planning", detail: "Choosing search strategy..." };
    case "Classifying":
      return { label: "Searching", detail: "Querying knowledge base..." };
    case "Searching":
    case "Browsing":
      return { label: "Evaluating", detail: "Assessing result relevance..." };
    case "Researching":
      return { label: "Analyzing", detail: "Reviewing rated results..." };
    case "Evaluating":
      return { label: "Analyzing", detail: "Deciding next step..." };
    case "Reformulating":
      return { label: "Searching", detail: "Retrying with new queries..." };
    case "Terminology":
      return { label: "Applying", detail: "Incorporating terminology..." };
    case "Drafting":
      return { label: "Finalizing", detail: "Preparing final answer..." };
    case "Critiquing":
      return { label: "Revising", detail: "Addressing critique feedback..." };
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
