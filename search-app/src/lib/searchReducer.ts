import type {
  ConversationTurn,
  DoneEvent,
  ErrorEvent,
  Iteration,
  MetadataEvent,
  ProgressEvent,
  SearchState,
  SubIterationEvent,
  ToolProgressEvent,
} from "./types";
import { initialSearchState } from "./types";

export type SearchAction =
  | { type: "SEARCH_START"; query: string; sessionId: string | null; history: ConversationTurn[] }
  | { type: "SEARCH_CONNECTED"; searchId: string; sessionId: string }
  | { type: "SSE_METADATA"; event: MetadataEvent }
  | { type: "SSE_ITERATION"; event: Iteration }
  | { type: "SSE_SUB_ITERATION"; event: SubIterationEvent }
  | { type: "SSE_TOOL_PROGRESS"; event: ToolProgressEvent }
  | { type: "SSE_PROGRESS"; event: ProgressEvent }
  | { type: "SSE_DONE"; event: DoneEvent }
  | { type: "SSE_ERROR"; event: ErrorEvent }
  | { type: "SSE_CANCELLED" }
  | { type: "CANCEL_START" }
  | { type: "CANCEL_TIMEOUT" }
  | { type: "NEW_SESSION" }
  | { type: "LOAD_LOG"; payload: Partial<SearchState> };

export function searchReducer(state: SearchState, action: SearchAction): SearchState {
  switch (action.type) {
    case "SEARCH_START":
      return {
        ...initialSearchState,
        status: "searching",
        query: action.query,
        sessionId: action.sessionId,
        conversationHistory: action.history,
      };

    case "SEARCH_CONNECTED":
      return { ...state, searchId: action.searchId, sessionId: action.sessionId };

    case "SSE_METADATA":
      return { ...state, metadata: action.event };

    case "SSE_ITERATION":
      return {
        ...state,
        iterations: [...state.iterations, action.event],
        toolProgress: [],
        subIterations: [],
      };

    case "SSE_SUB_ITERATION":
      return { ...state, subIterations: [...state.subIterations, action.event] };

    case "SSE_TOOL_PROGRESS":
      return { ...state, toolProgress: [...state.toolProgress, action.event] };

    case "SSE_PROGRESS":
      return { ...state, progressSteps: [...state.progressSteps, action.event] };

    case "SSE_DONE": {
      const turn: ConversationTurn = {
        query: state.query,
        answer: action.event.answer,
        sources: action.event.sources,
        searchId: state.searchId ?? "",
        executionTime: action.event.execution_time,
        status: "done",
        iterations: state.iterations,
        metadata: state.metadata,
        subIterations: state.subIterations,
        toolProgress: state.toolProgress,
        usage: action.event.usage,
        error: null,
      };
      return {
        ...state,
        status: "done",
        answer: action.event.answer,
        sources: action.event.sources,
        executionTime: action.event.execution_time,
        usage: action.event.usage,
        conversationHistory: [...state.conversationHistory, turn],
      };
    }

    case "SSE_ERROR": {
      const errorTurn: ConversationTurn = {
        query: state.query,
        answer: null,
        sources: [],
        searchId: state.searchId ?? "",
        executionTime: null,
        status: "error",
        iterations: state.iterations,
        metadata: state.metadata,
        subIterations: state.subIterations,
        toolProgress: state.toolProgress,
        usage: null,
        error: action.event.message,
      };
      return {
        ...state,
        status: "error",
        error: action.event.message,
        conversationHistory: [...state.conversationHistory, errorTurn],
      };
    }

    case "SSE_CANCELLED":
      return {
        ...initialSearchState,
        sessionId: state.sessionId,
        conversationHistory: state.conversationHistory,
      };

    case "CANCEL_START":
      return { ...state, status: "cancelling" };

    case "CANCEL_TIMEOUT":
      if (state.status === "cancelling") {
        return {
          ...initialSearchState,
          sessionId: state.sessionId,
          conversationHistory: state.conversationHistory,
        };
      }
      return state;

    case "NEW_SESSION":
      return initialSearchState;

    case "LOAD_LOG":
      return { ...initialSearchState, ...action.payload };
  }
}
