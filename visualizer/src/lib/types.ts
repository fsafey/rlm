// Types matching the RLM log format

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

export interface REPLResult {
  stdout: string;
  stderr: string;
  locals: Record<string, unknown>;
  execution_time: number;
  rlm_calls: RLMChatCompletion[];
}

export interface CodeBlock {
  code: string;
  result: REPLResult;
}

export interface RLMIteration {
  type?: string;
  iteration: number;
  timestamp: string;
  prompt: Array<{ role: string; content: string }>;
  response: string;
  code_blocks: CodeBlock[];
  final_answer: string | [string, string] | null;
  iteration_time: number | null;
}

// Metadata saved at the start of a log file about RLM configuration
export interface RLMConfigMetadata {
  root_model: string | null;
  max_depth: number | null;
  max_iterations: number | null;
  backend: string | null;
  backend_kwargs: Record<string, unknown> | null;
  environment_type: string | null;
  environment_kwargs: Record<string, unknown> | null;
  other_backends: string[] | null;
}

export interface RLMLogFile {
  fileName: string;
  filePath: string;
  iterations: RLMIteration[];
  metadata: LogMetadata;
  config: RLMConfigMetadata;
}

export interface LogMetadata {
  totalIterations: number;
  totalCodeBlocks: number;
  totalSubLMCalls: number;
  contextQuestion: string;
  finalAnswer: string | null;
  totalExecutionTime: number;
  hasErrors: boolean;
}

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

