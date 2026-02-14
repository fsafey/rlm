import { useState, useEffect, useRef, useMemo } from "react";
import {
  Loader2,
  CheckCircle2,
  Search,
  BookOpen,
  Brain,
  ChevronDown,
  MessageSquare,
  Sparkles,
  RefreshCw,
  ShieldCheck,
  Tag,
  Gauge,
} from "lucide-react";
import type { Iteration, MetadataEvent, ProgressEvent } from "@/lib/types";

interface SearchProgressProps {
  query: string;
  iterations: Iteration[];
  metadata: MetadataEvent | null;
  progressSteps: ProgressEvent[];
}

// --- Confidence ring ---

function ConfidenceRing({ value, size = 40 }: { value: number; size?: number }) {
  const radius = (size - 4) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (value / 100) * circumference;
  const color =
    value >= 60 ? "text-emerald-500" : value >= 30 ? "text-amber-500" : "text-rose-400";

  return (
    <div
      className="relative inline-flex items-center justify-center"
      style={{ width: size, height: size }}
    >
      <svg className="transform -rotate-90" width={size} height={size}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          className="stroke-muted"
          strokeWidth={3}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          className={`${color} transition-all duration-700 ease-out`}
          stroke="currentColor"
          strokeWidth={3}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
        />
      </svg>
      <span className={`absolute text-[10px] font-bold ${color}`}>{value}%</span>
    </div>
  );
}

// --- Progress phase rendering ---

const PHASE_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  reasoning: Brain,
  classifying: Tag,
  classified: Tag,
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
function detectActivityFromStdout(iteration: Iteration): IterationActivity {
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
    const dualMatch = stdout.match(/\[critique_answer\] dual-review verdict=(\w+)(.*)/);
    if (dualMatch) {
      const dualVerdict = dualMatch[1];
      const failedParts = dualMatch[2]; // e.g., " (failed: content, citations)"
      return {
        label: "Critiquing",
        metric: `Dual-review: ${dualVerdict}${failedParts || ""}`,
        icon: ShieldCheck,
      };
    }
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

  if (stdout.includes("[check_progress]")) {
    const confidence = extractMetric(stdout, /confidence=(\d+)%/);
    const guidance = extractMetric(stdout, /\[check_progress\] \w+ — (.+)/);
    let metric = guidance ?? "Assessed search progress";
    if (confidence) metric = `${confidence}% confidence — ${metric}`;
    return { label: "Checking Progress", metric, icon: Gauge };
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

/**
 * Detect iteration activity from structured tool_calls data.
 * Maps tool names to the same IterationActivity labels as the stdout-based detection.
 */
function detectActivityFromToolCalls(iteration: Iteration): IterationActivity {
  const calls = iteration.tool_calls ?? [];
  if (calls.length === 0) {
    return detectActivityFromStdout(iteration);
  }

  if (iteration.final_answer) {
    return { label: "Answer", metric: "Synthesized final answer", icon: MessageSquare };
  }

  // Find the primary (top-level) tool call — one without a parent
  const childIndices = new Set(calls.flatMap((c) => c.children));
  const topLevel = calls.filter((_, idx) => !childIndices.has(idx));
  const primary = topLevel[topLevel.length - 1] ?? calls[calls.length - 1];

  switch (primary.tool) {
    case "draft_answer": {
      const s = primary.result_summary;
      const passed = s.passed as boolean | undefined;
      const revised = s.revised as boolean | undefined;
      let metric = passed ? "Drafted and verified" : "Drafted, needs revision";
      if (revised) metric = "Drafted, revised, and verified";
      return { label: "Drafting", metric, icon: MessageSquare };
    }
    case "research": {
      const s = primary.result_summary;
      const searchCount = s.search_count as number | undefined;
      const evalSummary = s.eval_summary as string | undefined;
      const metric = evalSummary
        ? `${searchCount ?? "?"} searches — ${evalSummary}`
        : `${searchCount ?? "Multiple"} searches run`;
      return { label: "Researching", metric, icon: Search };
    }
    case "evaluate_results": {
      const s = primary.result_summary;
      const numRated = s.num_rated as number | undefined;
      const relevant = s.relevant as number | undefined;
      const partial = s.partial as number | undefined;
      const offTopic = s.off_topic as number | undefined;
      const metric = numRated != null
        ? `${relevant ?? 0} relevant, ${partial ?? 0} partial, ${offTopic ?? 0} off-topic`
        : "Rated search results";
      return { label: "Evaluating", metric, icon: ShieldCheck };
    }
    case "critique_answer": {
      const verdict = primary.result_summary.verdict as string | undefined;
      return {
        label: "Critiquing",
        metric: verdict ? `Verdict: ${verdict}` : "Reviewed draft",
        icon: ShieldCheck,
      };
    }
    case "batched_critique": {
      const s = primary.result_summary;
      const verdict = s.verdict as string | undefined;
      const contentOk = s.content_passed as boolean | undefined;
      const citationOk = s.citation_passed as boolean | undefined;
      let metric = verdict ? `Dual-review: ${verdict}` : "Dual-reviewer critique";
      if (verdict === "FAIL" && contentOk !== undefined && citationOk !== undefined) {
        const failed = [];
        if (!contentOk) failed.push("content");
        if (!citationOk) failed.push("citations");
        metric = `Dual-review FAIL (${failed.join(", ")})`;
      }
      return { label: "Critiquing", metric, icon: ShieldCheck };
    }
    case "reformulate": {
      const count = primary.result_summary.num_queries as number | undefined;
      return {
        label: "Reformulating",
        metric: count ? `${count} alternative queries` : "Generated alternatives",
        icon: RefreshCw,
      };
    }
    case "classify_question":
      return { label: "Classifying", metric: "Identified category and strategy", icon: Tag };
    case "check_progress": {
      const s = primary.result_summary;
      const confidence = s.confidence as number | undefined;
      const relevant = s.relevant as number | undefined;
      const metric =
        confidence != null
          ? `${confidence}% confidence — ${relevant ?? 0} relevant sources`
          : (s.phase as string) ?? "Assessed progress";
      return { label: "Checking Progress", metric, icon: Gauge };
    }
    case "search": {
      const s = primary.result_summary;
      const numResults = s.num_results as number | undefined;
      const query = primary.args.query as string | undefined;
      const truncated = query && query.length > 35 ? `${query.slice(0, 35)}...` : query;
      const metric = numResults != null
        ? `${numResults} results${truncated ? ` for "${truncated}"` : ""}`
        : "Queried knowledge base";
      return { label: "Searching", metric, icon: Search };
    }
    case "browse": {
      const total = primary.result_summary.total as number | undefined;
      const metric = total != null ? `${total} documents browsed` : "Browsed knowledge base";
      return { label: "Browsing", metric, icon: Search };
    }
    case "fiqh_lookup": {
      const bridges = primary.result_summary.num_bridges as number | undefined;
      const query = primary.args.query as string | undefined;
      const metric = bridges != null
        ? `${bridges} term bridges${query ? ` for "${query.slice(0, 30)}"` : ""}`
        : "Looked up terminology";
      return { label: "Terminology", metric, icon: BookOpen };
    }
    case "kb_overview":
      return { label: "Exploring KB", metric: "Reviewing taxonomy and categories", icon: BookOpen };
    default: {
      const blockCount = iteration.code_blocks.length;
      return {
        label: "Processing",
        metric: `${blockCount} code block${blockCount !== 1 ? "s" : ""} executed`,
        icon: Sparkles,
      };
    }
  }
}

function detectActivity(iteration: Iteration): IterationActivity {
  if (iteration.tool_calls && iteration.tool_calls.length > 0) {
    return detectActivityFromToolCalls(iteration);
  }
  return detectActivityFromStdout(iteration);
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
    case "Checking Progress":
      return { label: "Planning", detail: "Deciding next step based on progress..." };
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

  const latestConfidence = useMemo(() => {
    for (let i = iterations.length - 1; i >= 0; i--) {
      const calls = iterations[i].tool_calls ?? [];
      const cp = calls.find((c) => c.tool === "check_progress");
      if (cp?.result_summary?.confidence != null) {
        return cp.result_summary.confidence as number;
      }
    }
    return null;
  }, [iterations]);

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
        {/* Header — reflects current stage */}
        <div className="px-6 py-4 border-b border-border">
          <h2 className="text-sm font-semibold text-foreground tracking-tight">
            {activeText.label}
          </h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            {activeText.detail}
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
                  duration={item.step.duration_ms ? `${item.step.duration_ms}ms` : undefined}
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
        <div className="px-6 py-3 bg-muted/50 border-t border-border flex items-center justify-between text-xs text-muted-foreground">
          <span>
            {iterations.length}/{maxIterations} iterations
          </span>
          {latestConfidence != null && <ConfidenceRing value={latestConfidence} size={36} />}
          <span>{(elapsedMs / 1000).toFixed(1)}s elapsed</span>
        </div>
      </div>
    </div>
  );
}
