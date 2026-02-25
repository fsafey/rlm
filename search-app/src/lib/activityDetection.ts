import type { ComponentType } from "react";
import {
  Search,
  BookOpen,
  Brain,
  MessageSquare,
  Sparkles,
  RefreshCw,
  ShieldCheck,
  Tag,
  Gauge,
} from "lucide-react";
import type { Iteration, ToolProgressEvent, ToolStartEvent, ToolEndEvent } from "@/lib/types";

export interface IterationActivity {
  label: string;
  metric: string;
  icon: ComponentType<{ className?: string }>;
}

export const PHASE_ICON: Record<string, ComponentType<{ className?: string }>> = {
  reasoning: Brain,
  classifying: Tag,
  classified: Tag,
  env_ready: Sparkles,
};

export function formatToolProgress(events: ToolProgressEvent[]): { label: string; detail: string } | null {
  if (events.length === 0) return null;

  const latest = events[events.length - 1];
  const { tool, phase, data } = latest;

  // Synthetic lifecycle events from RLM core
  if (tool === "_llm") {
    return { label: "Waiting for model", detail: "This is usually the longest step..." };
  }
  if (tool === "_code") {
    const n = data.num_blocks as number | undefined;
    return {
      label: "Executing code",
      detail: n ? `Model responded — ${n} block${n !== 1 ? "s" : ""}` : "Model responded",
    };
  }

  // Real tool events
  if (phase === "start") {
    const query = data.query as string | undefined;
    const truncated = query && query.length > 35 ? `${query.slice(0, 35)}...` : query;
    switch (tool) {
      case "search":
        return { label: "Searching", detail: truncated ? `'${truncated}'` : "Querying KB" };
      case "browse":
        return { label: "Browsing", detail: "Scanning knowledge base" };
      case "evaluate_results":
        return { label: "Evaluating", detail: "Rating result relevance" };
      case "research":
        return { label: "Researching", detail: truncated ? `'${truncated}'` : "Multi-search" };
      case "draft_answer":
        return { label: "Drafting", detail: "Synthesizing answer from evidence" };
      case "critique_answer":
      case "batched_critique":
        return { label: "Critiquing", detail: "Reviewing draft quality" };
      case "reformulate":
        return { label: "Reformulating", detail: "Generating alternative queries" };
      case "rlm_query": {
        const sub = data.sub_question as string | undefined;
        return { label: "Delegating", detail: sub ? `Researching: "${sub.slice(0, 40)}"` : "Sub-agent research" };
      }
      case "check_progress":
        return { label: "Checking progress", detail: "Assessing search confidence" };
      case "fiqh_lookup":
        return { label: "Terminology", detail: truncated ? `'${truncated}'` : "Looking up terms" };
      default:
        return { label: `Running ${tool}`, detail: "" };
    }
  }

  if (phase === "end") {
    const dur = latest.duration_ms ? ` (${latest.duration_ms}ms)` : "";
    switch (tool) {
      case "search": {
        const n = data.num_results as number | undefined;
        return { label: "Searching", detail: `${n ?? "?"} results found${dur}` };
      }
      case "evaluate_results": {
        const r = data.relevant as number | undefined;
        const p = data.partial as number | undefined;
        return { label: "Evaluating", detail: `${r ?? 0} relevant, ${p ?? 0} partial${dur}` };
      }
      case "rlm_query": {
        const sc = data.searches_run as number | undefined;
        const merged = data.sources_merged as number | undefined;
        return { label: "Delegating", detail: `${sc ?? "?"} searches, ${merged ?? 0} sources merged${dur}` };
      }
      case "research": {
        const sc = data.search_count as number | undefined;
        const f = data.filtered as number | undefined;
        return { label: "Researching", detail: `${sc ?? "?"} searches, ${f ?? "?"} filtered${dur}` };
      }
      case "draft_answer": {
        const passed = data.passed as boolean | undefined;
        return { label: "Drafting", detail: passed ? `Critique passed${dur}` : `Critique failed${dur}` };
      }
      case "critique_answer":
      case "batched_critique": {
        const v = data.verdict as string | undefined;
        return { label: "Critiquing", detail: `${v ?? "Done"}${dur}` };
      }
      default:
        return { label: tool, detail: `Done${dur}` };
    }
  }

  return null;
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

  // --- Delegation (check before composite tools) ---

  if (stdout.includes("[rlm_query]")) {
    const sub = stdout.match(/Delegating: "(.+?)"/)?.[1];
    const metric = sub ?? "Delegating sub-question to research agent";
    return { label: "Delegating", metric, icon: Brain };
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
    case "rlm_query": {
      const s = primary.result_summary;
      const sub = (s?.sub_question as string) ?? "Sub-question";
      const sc = s?.searches_run as number;
      const metric = sc != null ? `${sub} (${sc} searches)` : sub;
      return { label: "Delegating", metric, icon: Brain };
    }
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
    case "critique_answer":
    case "batched_critique": {
      const verdict = primary.result_summary.verdict as string | undefined;
      return {
        label: "Critiquing",
        metric: verdict ? `Verdict: ${verdict}` : "Reviewed draft",
        icon: ShieldCheck,
      };
    }
    case "reformulate": {
      const count = primary.result_summary.num_queries as number | undefined;
      return {
        label: "Reformulating",
        metric: count ? `${count} alternative queries` : "Generated alternatives",
        icon: RefreshCw,
      };
    }
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

export function detectActivity(iteration: Iteration): IterationActivity {
  if (iteration.tool_calls && iteration.tool_calls.length > 0) {
    return detectActivityFromToolCalls(iteration);
  }
  return detectActivityFromStdout(iteration);
}

/**
 * Detect activity from typed tool_start / tool_end events emitted by EventBus.
 *
 * Maps tool names directly to IterationActivity values, avoiding stdout parsing.
 * Returns null for unrecognised tool names so callers can fall back to other methods.
 */
export function detectActivityFromEvent(
  event: ToolStartEvent | ToolEndEvent,
): IterationActivity | null {
  const { tool } = event.data;
  const isEnd = event.type === "tool_end";

  switch (tool) {
    case "rlm_query": {
      if (isEnd) {
        const d = (event as ToolEndEvent).data;
        const sc = d.result_summary?.searches_run as number | undefined;
        const metric = sc != null ? `Sub-agent: ${sc} searches` : "Delegated sub-question";
        return { label: "Delegating", metric, icon: Brain };
      }
      const sub = (event as ToolStartEvent).data.args?.sub_question as string | undefined;
      return { label: "Delegating", metric: sub ?? "Delegating sub-question", icon: Brain };
    }
    case "draft_answer": {
      if (isEnd) {
        const d = (event as ToolEndEvent).data;
        const passed = d.result_summary?.passed as boolean | undefined;
        const revised = d.result_summary?.revised as boolean | undefined;
        let metric = passed ? "Drafted and verified" : "Drafted, needs revision";
        if (revised) metric = "Drafted, revised, and verified";
        return { label: "Drafting", metric, icon: MessageSquare };
      }
      return { label: "Drafting", metric: "Synthesizing answer from evidence", icon: MessageSquare };
    }
    case "research": {
      if (isEnd) {
        const d = (event as ToolEndEvent).data;
        const sc = d.result_summary?.search_count as number | undefined;
        const evalSummary = d.result_summary?.eval_summary as string | undefined;
        const metric = evalSummary
          ? `${sc ?? "?"} searches — ${evalSummary}`
          : `${sc ?? "Multiple"} searches run`;
        return { label: "Researching", metric, icon: Search };
      }
      const query = (event as ToolStartEvent).data.args?.query as string | undefined;
      const truncated = query && query.length > 35 ? `${query.slice(0, 35)}...` : query;
      return { label: "Researching", metric: truncated ? `'${truncated}'` : "Multi-search", icon: Search };
    }
    case "evaluate_results": {
      if (isEnd) {
        const d = (event as ToolEndEvent).data;
        const r = d.result_summary?.relevant as number | undefined;
        const p = d.result_summary?.partial as number | undefined;
        return { label: "Evaluating", metric: `${r ?? 0} relevant, ${p ?? 0} partial`, icon: ShieldCheck };
      }
      return { label: "Evaluating", metric: "Rating result relevance", icon: ShieldCheck };
    }
    case "critique_answer":
    case "batched_critique": {
      if (isEnd) {
        const d = (event as ToolEndEvent).data;
        const verdict = d.result_summary?.verdict as string | undefined;
        return { label: "Critiquing", metric: verdict ? `Verdict: ${verdict}` : "Reviewed draft", icon: ShieldCheck };
      }
      return { label: "Critiquing", metric: "Reviewing draft quality", icon: ShieldCheck };
    }
    case "reformulate": {
      if (isEnd) {
        const d = (event as ToolEndEvent).data;
        const count = d.result_summary?.num_queries as number | undefined;
        return { label: "Reformulating", metric: count ? `${count} alternative queries` : "Generated alternatives", icon: RefreshCw };
      }
      return { label: "Reformulating", metric: "Generating alternative queries", icon: RefreshCw };
    }
    case "check_progress": {
      if (isEnd) {
        const d = (event as ToolEndEvent).data;
        const confidence = d.result_summary?.confidence as number | undefined;
        const relevant = d.result_summary?.relevant as number | undefined;
        const metric = confidence != null
          ? `${confidence}% confidence — ${relevant ?? 0} relevant sources`
          : "Assessed progress";
        return { label: "Checking Progress", metric, icon: Gauge };
      }
      return { label: "Checking Progress", metric: "Assessing search confidence", icon: Gauge };
    }
    case "search": {
      if (isEnd) {
        const d = (event as ToolEndEvent).data;
        const n = d.result_summary?.num_results as number | undefined;
        return { label: "Searching", metric: n != null ? `${n} results found` : "Queried knowledge base", icon: Search };
      }
      const query = (event as ToolStartEvent).data.args?.query as string | undefined;
      const truncated = query && query.length > 35 ? `${query.slice(0, 35)}...` : query;
      return { label: "Searching", metric: truncated ? `'${truncated}'` : "Querying KB", icon: Search };
    }
    case "browse": {
      if (isEnd) {
        const d = (event as ToolEndEvent).data;
        const total = d.result_summary?.total as number | undefined;
        return { label: "Browsing", metric: total != null ? `${total} documents browsed` : "Browsed knowledge base", icon: Search };
      }
      return { label: "Browsing", metric: "Scanning knowledge base", icon: Search };
    }
    case "fiqh_lookup": {
      if (isEnd) {
        const d = (event as ToolEndEvent).data;
        const bridges = d.result_summary?.num_bridges as number | undefined;
        return { label: "Terminology", metric: bridges != null ? `${bridges} term bridges` : "Looked up terminology", icon: BookOpen };
      }
      const query = (event as ToolStartEvent).data.args?.query as string | undefined;
      return { label: "Terminology", metric: query ? `'${query.slice(0, 30)}'` : "Looking up terms", icon: BookOpen };
    }
    case "kb_overview":
      return { label: "Exploring KB", metric: "Reviewing taxonomy and categories", icon: BookOpen };
    default:
      return null;
  }
}

// --- Contextual active step based on what just happened ---

export function getActiveText(
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
    case "Delegating":
      return { label: "Researching", detail: "Sub-agent researching independently..." };
    case "Drafting":
      return { label: "Finalizing", detail: "Preparing final answer..." };
    case "Critiquing":
      return { label: "Revising", detail: "Addressing critique feedback..." };
    default:
      return { label: "Thinking", detail: "Processing..." };
  }
}
