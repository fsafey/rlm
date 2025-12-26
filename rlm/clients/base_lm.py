from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple

from dataclasses import dataclass


@dataclass
class CostSummary:
    total_calls: int
    total_cost: float
    total_input_tokens: int
    total_output_tokens: int


class BaseLM(ABC):
    """
    Base class for all language model routers / clients. When the RLM makes sub-calls, it currently
    does so in a model-agnostic way, so this class provides a base interface for all language models.
    """

    def __init__(self, model_name: str, **kwargs):
        self.model_name = model_name
        self.kwargs = kwargs

    @abstractmethod
    def completion(self, prompt: str | Dict[str, Any]) -> str:
        raise NotImplementedError

    @abstractmethod
    async def acompletion(self, prompt: str | Dict[str, Any]) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_cost_summary(self) -> CostSummary:
        """Get cost summary for all calls."""
        raise NotImplementedError

    @abstractmethod
    def get_last_usage(self) -> Tuple[int, int]:
        """Get the last usage of the model."""
        raise NotImplementedError
