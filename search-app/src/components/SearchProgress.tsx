import { useState, useEffect, useRef, useMemo } from "react";
import {
  Loader2,
  CheckCircle2,
  ChevronDown,
  Sparkles,
} from "lucide-react";
import type { Iteration, MetadataEvent, ProgressEvent, SubIterationEvent, ToolEndEvent, ToolProgressEvent, ToolStartEvent } from "@/lib/types";
import {
  detectActivity,
  detectActivityFromEvent,
  getActiveText,
  formatToolProgress,
  PHASE_ICON,
} from "@/lib/activityDetection";

interface SearchProgressProps {
  query: string;
  iterations: Iteration[];
  metadata: MetadataEvent | null;
  progressSteps: ProgressEvent[];
  toolProgress: ToolProgressEvent[];
  toolStartEvents: ToolStartEvent[];
  toolEndEvents: ToolEndEvent[];
  subIterations: SubIterationEvent[];
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

// --- Sub-agent steps (nested under delegation) ---

function SubAgentSteps({ subIterations }: { subIterations: SubIterationEvent[] }) {
  if (subIterations.length === 0) return null;

  return (
    <div className="ml-8 mt-2 space-y-1.5 border-l-2 border-primary/20 pl-3">
      <div className="text-xs font-medium text-primary/70 mb-1">
        Sub-agent: &ldquo;{subIterations[0].sub_question.slice(0, 50)}&rdquo;
      </div>
      {subIterations.map((sub, idx) => {
        const activity = detectActivity(sub as unknown as Iteration);
        return (
          <div key={idx} className="flex items-center gap-2 text-xs text-muted-foreground">
            <CheckCircle2 className="w-3 h-3 text-emerald-500/70" />
            <activity.icon className="w-3 h-3" />
            <span>{activity.label}</span>
            <span className="text-muted-foreground/60 truncate">{activity.metric}</span>
          </div>
        );
      })}
    </div>
  );
}

// --- Main component ---

export function SearchProgress({
  query,
  iterations,
  metadata,
  progressSteps,
  toolProgress,
  toolStartEvents,
  toolEndEvents,
  subIterations,
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

  // Derive active text from tool_start / tool_end events (EventBus path)
  const toolEventText = useMemo(() => {
    // Prefer the most recent tool event (start or end)
    const latestStart = toolStartEvents[toolStartEvents.length - 1];
    const latestEnd = toolEndEvents[toolEndEvents.length - 1];

    // If we have an end event newer than the latest start, show its result
    if (latestEnd && (!latestStart || latestEnd.timestamp >= latestStart.timestamp)) {
      const activity = detectActivityFromEvent(latestEnd);
      if (activity) {
        const dur = latestEnd.data.duration_ms ? ` (${latestEnd.data.duration_ms}ms)` : "";
        return { label: activity.label, detail: `${activity.metric}${dur}` };
      }
    }

    // Otherwise show the active tool_start
    if (latestStart) {
      const activity = detectActivityFromEvent(latestStart);
      if (activity) {
        return { label: activity.label, detail: activity.metric };
      }
    }

    return null;
  }, [toolStartEvents, toolEndEvents]);

  // Contextual active step — priority: tool events > tool progress > init progress > prediction
  const toolText = formatToolProgress(toolProgress);
  const activeText = toolEventText
    ? toolEventText
    : toolText
      ? toolText
      : activeProgress
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
          {activeText.label === "Delegating" && <SubAgentSteps subIterations={subIterations} />}
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
