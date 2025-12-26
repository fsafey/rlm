from rlm.clients import get_client, BaseLM
from rlm.environments import get_environment, BaseEnv
from rlm.core.lm_handler import LMHandler
from rlm.logger.rlm_logger import RLMLogger
from rlm.core.types import (
    RLMIteration,
    REPLResult,
    CodeBlock,
    ClientBackend,
    EnvironmentType,
)
from rlm.utils.prompts import (
    build_rlm_system_prompt,
    build_user_prompt,
    QueryMetadata,
    RLM_SYSTEM_PROMPT,
)
from rlm.utils.parsing import (
    find_code_blocks,
    find_final_answer,
    format_iteration,
)

from typing import Dict, Any, Optional, List
from contextlib import contextmanager


class RLM:
    """
    Recursive Language Model class that the user instantiates and runs on their tasks.

    Each completion() call spawns its own environment and LM handler, which are
    cleaned up when the call completes.
    """

    def __init__(
        self,
        backend: ClientBackend = "openai",
        backend_kwargs: Dict[str, Any] = {},
        environment: EnvironmentType = "local",
        environment_kwargs: Dict[str, Any] = {},
        depth: int = 0,
        max_depth: int = 1,
        max_iterations: int = 30,
        custom_system_prompt: Optional[str] = None,
        other_backends: Optional[List[ClientBackend]] = None,
        other_backend_kwargs: Optional[List[Dict[str, Any]]] = None,
        logger: Optional[RLMLogger] = None,
    ):
        """
        Args:
            backend: The backend to use for the RLM.
            backend_kwargs: The kwargs to pass to the backend.
            environment: The environment to use for the RLM.
            environment_kwargs: The kwargs to pass to the environment.
            depth: The current depth of the RLM (0-indexed).
            max_depth: The maximum depth of the RLM.
            max_iterations: The maximum number of iterations of the RLM.
            custom_system_prompt: The custom system prompt to use for the RLM.
            other_backends: A list of other client backends that the environments can use to make sub-calls.
            other_backend_kwargs: The kwargs to pass to the other client backends (ordered to match other_backends).
            logger: The logger to use for the RLM.
        """
        # Store config for spawning per-completion
        self.backend = backend
        self.backend_kwargs = backend_kwargs
        self.environment_type = environment
        self.environment_kwargs = environment_kwargs.copy()
        self.other_backends = other_backends
        self.other_backend_kwargs = other_backend_kwargs

        self.depth = depth
        self.max_depth = max_depth
        self.max_iterations = max_iterations
        self.system_prompt = (
            custom_system_prompt if custom_system_prompt else RLM_SYSTEM_PROMPT
        )
        self.logger = logger

    @contextmanager
    def _spawn_completion_context(self, prompt: str | Dict[str, Any]):
        """
        Spawn an LM handler and environment for a single completion call.
        Cleans up both when the context exits.
        """
        # Create client and wrap in handler
        client: BaseLM = get_client(self.backend, self.backend_kwargs)
        lm_handler = LMHandler(client)

        # Register other clients to be available as sub-call options
        if self.other_backends and self.other_backend_kwargs:
            for backend, kwargs in zip(self.other_backends, self.other_backend_kwargs):
                other_client: BaseLM = get_client(backend, kwargs)
                lm_handler.register_client(other_client.model_name, other_client)

        lm_handler.start()

        # Pass handler address to environment so it can make llm_query() calls
        env_kwargs = self.environment_kwargs.copy()
        env_kwargs["lm_handler_address"] = (lm_handler.host, lm_handler.port)
        env_kwargs["context_payload"] = prompt

        # Initialize the environment
        environment: BaseEnv = get_environment(self.environment_type, env_kwargs)

        try:
            yield lm_handler, environment
        finally:
            # Cleanup
            lm_handler.stop()
            if hasattr(environment, "cleanup"):
                environment.cleanup()

    def _setup_prompt(self, prompt: str | Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Setup the system prompt for the RLM. Also include metadata about the prompt and build
        up the initial message history.
        """
        metadata = QueryMetadata(prompt)
        message_history = build_rlm_system_prompt(
            system_prompt=self.system_prompt, query_metadata=metadata
        )

        return message_history

    def completion(
        self, prompt: str | Dict[str, Any], root_prompt: Optional[str] = None
    ) -> str:
        """
        Recursive Language Model completion call. This is the main entry point for querying an RLM, and
        can replace a regular LM completion call.

        Spawns its own environment and LM handler for the duration of this call.

        Args:
            prompt: A single string or dictionary of messages to pass as context to the model.
            root_prompt: We allow the RLM's root LM to see a (small) prompt that the user specifies. A common example of this
            is if the user is asking the RLM to answer a question, we can pass the question as the root prompt.
        Returns:
            A final answer as a string.
        """
        with self._spawn_completion_context(prompt) as (lm_handler, environment):
            message_history = self._setup_prompt(prompt)

            for i in range(self.max_iterations):
                # Current prompt = message history + additional prompt suffix
                current_prompt = message_history + [build_user_prompt(root_prompt, i)]

                iteration: RLMIteration = self._completion_turn(
                    prompt=current_prompt,
                    lm_handler=lm_handler,
                    environment=environment,
                )

                # Check if RLM is done and has a final answer.
                final_answer = find_final_answer(iteration.response)
                iteration.final_answer = final_answer

                # If logger is used, log the iteration.
                if self.logger:
                    self.logger.log(iteration)

                if final_answer:
                    return final_answer

                # Format the iteration for the next prompt.
                new_messages = format_iteration(iteration)

                # Update message history with the new messages.
                message_history.extend(new_messages)

            # Default behavior: we run out of iterations, provide one final answer
            final_answer = self._default_answer(message_history, lm_handler)
            return final_answer

    def _completion_turn(
        self,
        prompt: str | Dict[str, Any],
        lm_handler: LMHandler,
        environment: BaseEnv,
    ) -> RLMIteration:
        """
        Perform a single iteration of the RLM, including prompting the model
        and code execution + tool execution.
        """
        response = lm_handler.completion(prompt)
        code_block_strs = find_code_blocks(response)
        code_blocks = []

        for code_block_str in code_block_strs:
            code_result: REPLResult = environment.execute_code(code_block_str)
            code_blocks.append(CodeBlock(code=code_block_str, result=code_result))

        return RLMIteration(prompt=prompt, response=response, code_blocks=code_blocks)

    def _default_answer(
        self, message_history: List[Dict[str, Any]], lm_handler: LMHandler
    ) -> str:
        """
        Default behavior if the RLM runs out of iterations and does not find a final answer.
        It will take the message history, and try to generate a final answer from it.
        """
        current_prompt = message_history + [
            {
                "role": "assistant",
                "content": "Please provide a final answer to the user's question based on the information provided.",
            }
        ]
        response = lm_handler.completion(current_prompt)

        if self.logger:
            self.logger.log(
                RLMIteration(
                    prompt=current_prompt,
                    response=response,
                    final_answer=response,
                    code_blocks=[],
                )
            )

        return response
