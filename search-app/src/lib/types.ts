export interface SearchSource {
  id: string;
  question: string;
  answer: string;
  score: number;
  metadata: Record<string, unknown>;
}

export interface CodeBlockResult {
  stdout: string;
  stderr: string;
  locals: Record<string, unknown>;
  execution_time: number;
  rlm_calls: unknown[];
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
  model: "claude-sonnet-4-20250514",
  max_iterations: 15,
};

export const initialSearchState: SearchState = {
  status: "idle",
  searchId: null,
  query: "",
  iterations: [],
  answer: null,
  sources: [],
  executionTime: null,
  usage: null,
  error: null,
};
