from dataclasses import dataclass
from typing import Literal, List, Dict, Any, Optional
from types import ModuleType

ClientBackend = Literal["openai", "portkey"]
EnvironmentType = Literal["local", "prime", "modal"]


def _serialize_value(value: Any) -> Any:
    """Convert a value to a JSON-serializable representation."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, ModuleType):
        return f"<module '{value.__name__}'>"
    if isinstance(value, (list, tuple)):
        return [_serialize_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _serialize_value(v) for k, v in value.items()}
    if callable(value):
        return f"<{type(value).__name__} '{getattr(value, '__name__', repr(value))}'>"
    # Try to convert to string for other types
    try:
        return repr(value)
    except Exception:
        return f"<{type(value).__name__}>"


########################################################
########   Types for REPL and RLM Iterations   #########
########################################################
@dataclass
class RLMChatCompletion:
    """Record of a single LLM call made from within the environment."""

    prompt: str | Dict[str, Any]
    response: str
    prompt_tokens: int
    completion_tokens: int
    execution_time: float

    def to_dict(self):
        return {
            "prompt": self.prompt,
            "response": self.response,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "execution_time": self.execution_time,
        }


@dataclass
class REPLResult:
    stdout: str
    stderr: str
    locals: dict
    execution_time: float
    llm_calls: List["RLMChatCompletion"]

    def __init__(
        self,
        stdout: str,
        stderr: str,
        locals: dict,
        execution_time: float = None,
        rlm_calls: List["RLMChatCompletion"] = None,
    ):
        self.stdout = stdout
        self.stderr = stderr
        self.locals = locals
        self.execution_time = execution_time
        self.rlm_calls = rlm_calls or []

    def __str__(self):
        return f"REPLResult(stdout={self.stdout}, stderr={self.stderr}, locals={self.locals}, execution_time={self.execution_time}, rlm_calls={len(self.rlm_calls)})"

    def to_dict(self):
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "locals": {k: _serialize_value(v) for k, v in self.locals.items()},
            "execution_time": self.execution_time,
            "rlm_calls": [call.to_dict() for call in self.rlm_calls],
        }


@dataclass
class CodeBlock:
    code: str
    result: REPLResult

    def to_dict(self):
        return {"code": self.code, "result": self.result.to_dict()}


@dataclass
class RLMIteration:
    prompt: str | Dict[str, Any]
    response: str
    code_blocks: List[CodeBlock]
    final_answer: Optional[str] = None

    def to_dict(self):
        return {
            "prompt": self.prompt,
            "response": self.response,
            "code_blocks": [code_block.to_dict() for code_block in self.code_blocks],
            "final_answer": self.final_answer,
        }


########################################################
########   Types for RLM Prompting   #########
########################################################


@dataclass
class QueryMetadata:
    context_lengths: List[int]
    context_total_length: int
    context_type: str

    def __init__(self, prompt: str | List[str] | Dict[Any, str] | List[Dict[Any, str]]):
        if isinstance(prompt, str):
            self.context_lengths = [len(prompt)]
            self.context_type = "str"
        elif isinstance(prompt, Dict[Any, str]):
            self.context_lengths = [len(chunk) for chunk in prompt.values()]
            self.context_type = "dict"
        elif isinstance(prompt, list):
            self.context_type = "list"
            if isinstance(prompt[0], dict):
                if "content" in prompt[0]:
                    self.context_lengths = [len(chunk["content"]) for chunk in prompt]
                else:
                    self.context_lengths = [len(chunk) for chunk in prompt]
            else:
                self.context_lengths = [len(chunk) for chunk in prompt]
        else:
            raise ValueError(f"Invalid prompt type: {type(prompt)}")

        self.context_total_length = sum(self.context_lengths)
