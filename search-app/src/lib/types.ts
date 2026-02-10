export interface SearchSource {
  id: string;
  question: string;
  answer: string;
  score: number;
  metadata: Record<string, unknown>;
}

export interface ModelUsageSummary {
  total_calls: number;
  total_input_tokens: number;
  total_output_tokens: number;
}

export interface UsageSummary {
  model_usage_summaries: Record<string, ModelUsageSummary>;
}

export interface RLMChatCompletion {
  root_model?: string;
  prompt: string | Record<string, unknown>;
  response: string;
  usage_summary?: UsageSummary;
  execution_time?: number;
}

export interface CodeBlockResult {
  stdout: string;
  stderr: string;
  locals: Record<string, unknown>;
  execution_time: number;
  rlm_calls: RLMChatCompletion[];
}

export interface CodeBlock {
  code: string;
  result: CodeBlockResult;
}

export interface Iteration {
  type: "iteration";
  iteration: number;
  timestamp: string;
  response: string;
  code_blocks: CodeBlock[];
  final_answer: string | null;
  iteration_time: number | null;
}

export interface MetadataEvent {
  type: "metadata";
  root_model: string;
  max_depth: number;
  max_iterations: number;
  backend: string;
}

export interface DoneEvent {
  type: "done";
  answer: string;
  sources: SearchSource[];
  execution_time: number;
  usage: Record<string, unknown>;
}

export interface ErrorEvent {
  type: "error";
  message: string;
}

export type SSEEvent = MetadataEvent | Iteration | DoneEvent | ErrorEvent;

export interface SearchState {
  status: "idle" | "searching" | "done" | "error";
  searchId: string | null;
  query: string;
  metadata: MetadataEvent | null;
  iterations: Iteration[];
  answer: string | null;
  sources: SearchSource[];
  executionTime: number | null;
  usage: Record<string, unknown> | null;
  error: string | null;
}

export interface SearchSettings {
  model: string;
  max_iterations: number;
}

export const defaultSettings: SearchSettings = {
  model: "claude-sonnet-4-5-20250929",
  max_iterations: 15,
};

export const initialSearchState: SearchState = {
  status: "idle",
  searchId: null,
  query: "",
  metadata: null,
  iterations: [],
  answer: null,
  sources: [],
  executionTime: null,
  usage: null,
  error: null,
};

export function extractFinalAnswer(answer: string | [string, string] | null): string | null {
  if (!answer) return null;
  if (Array.isArray(answer)) {
    return answer[1];
  }
  return answer;
}

/** Extract total input/output tokens from a sub-LM call's usage summary. */
export function extractTokens(call: RLMChatCompletion): { input: number; output: number } {
  const summaries = call.usage_summary?.model_usage_summaries;
  if (!summaries) return { input: 0, output: 0 };
  let input = 0;
  let output = 0;
  for (const usage of Object.values(summaries)) {
    input += usage.total_input_tokens ?? 0;
    output += usage.total_output_tokens ?? 0;
  }
  return { input, output };
}
