import asyncio
import json
import os
import subprocess
from collections import defaultdict
from typing import Any

from rlm.clients.base_lm import BaseLM
from rlm.core.types import ModelUsageSummary, UsageSummary


class ClaudeCLI(BaseLM):
    """BaseLM client that shells out to `claude -p` (Claude Code CLI).

    Uses the user's authenticated Claude Code session -- no API key needed.
    Uses JSON output format to capture token usage and cost data.
    """

    def __init__(
        self,
        model_name: str = "claude-cli",
        model: str | None = None,
        timeout: int = 300,
        max_budget_usd: float | None = None,
        permission_mode: str | None = None,
        allowed_tools: list[str] | None = None,
        tools: str = "",
        extra_flags: list[str] | None = None,
        **kwargs,
    ):
        super().__init__(model_name=model_name, **kwargs)
        self.model = model
        self.timeout = timeout
        self.max_budget_usd = max_budget_usd
        self.permission_mode = permission_mode
        self.allowed_tools = allowed_tools
        self.tools = tools
        self.extra_flags = extra_flags
        self._model_call_counts: dict[str, int] = defaultdict(int)
        self._model_input_tokens: dict[str, int] = defaultdict(int)
        self._model_output_tokens: dict[str, int] = defaultdict(int)
        self._last_input_tokens: int = 0
        self._last_output_tokens: int = 0

    def _build_prompt(
        self, prompt: str | list[dict[str, Any]] | dict[str, Any]
    ) -> tuple[str, str | None]:
        """Extract (prompt_text, system_prompt_or_none) from the input."""
        if isinstance(prompt, str):
            return prompt, None

        if isinstance(prompt, dict):
            return prompt.get("content", str(prompt)), None

        # list[dict] — chat-style messages
        system_prompt = None
        parts = []
        for msg in prompt:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_prompt = content
            else:
                parts.append(f"[{role}]: {content}")
        prompt_text = "\n\n".join(parts)
        return prompt_text, system_prompt

    def _build_cmd(
        self, prompt_text: str, system_prompt: str | None, model_override: str | None = None
    ) -> list[str]:
        """Build the CLI command list from instance config and per-call args."""
        cmd = [
            "claude",
            "-p",
            prompt_text,
            "--output-format",
            "json",
            "--no-session-persistence",
        ]
        if self.tools:
            cmd.extend(["--tools", self.tools])
        effective_model = model_override or self.model
        if effective_model:
            cmd.extend(["--model", effective_model])
        if self.max_budget_usd is not None:
            cmd.extend(["--max-budget-usd", str(self.max_budget_usd)])
        if self.permission_mode:
            cmd.extend(["--permission-mode", self.permission_mode])
        if self.allowed_tools:
            for tool in self.allowed_tools:
                cmd.extend(["--allowedTools", tool])
        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])
        if self.extra_flags:
            cmd.extend(self.extra_flags)
        return cmd

    @staticmethod
    def _clean_env() -> dict[str, str]:
        """Return env dict without CLAUDECODE to allow nested CLI invocations."""
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)
        return env

    def _parse_response(self, raw_output: str) -> str:
        """Parse JSON output from claude CLI, accumulate usage, return result text."""
        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"claude CLI returned non-JSON output (parse error: {e}). "
                f"Raw output: {raw_output[:500]}"
            ) from e
        result_text = data.get("result", "")

        # Accumulate per-model usage from modelUsage field
        model_usage = data.get("modelUsage", {})
        for model_key, usage in model_usage.items():
            input_tokens = usage.get("inputTokens", 0) + usage.get("cacheReadInputTokens", 0)
            output_tokens = usage.get("outputTokens", 0)
            self._model_call_counts[model_key] += 1
            self._model_input_tokens[model_key] += input_tokens
            self._model_output_tokens[model_key] += output_tokens

        # Track last-call usage from top-level usage field
        top_usage = data.get("usage", {})
        self._last_input_tokens = top_usage.get("input_tokens", 0) + top_usage.get(
            "cache_read_input_tokens", 0
        )
        self._last_output_tokens = top_usage.get("output_tokens", 0)

        return result_text

    def completion(
        self, prompt: str | list[dict[str, Any]] | dict[str, Any], model: str | None = None
    ) -> str:
        prompt_text, system_prompt = self._build_prompt(prompt)
        cmd = self._build_cmd(prompt_text, system_prompt, model_override=model)

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=self.timeout, env=self._clean_env()
        )
        if result.returncode != 0:
            raise RuntimeError(f"claude CLI failed (rc={result.returncode}): {result.stderr}")

        return self._parse_response(result.stdout)

    async def acompletion(
        self, prompt: str | list[dict[str, Any]] | dict[str, Any], model: str | None = None
    ) -> str:
        prompt_text, system_prompt = self._build_prompt(prompt)
        cmd = self._build_cmd(prompt_text, system_prompt, model_override=model)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._clean_env(),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)

        if proc.returncode != 0:
            raise RuntimeError(f"claude CLI failed (rc={proc.returncode}): {stderr.decode()}")

        return self._parse_response(stdout.decode())

    def get_usage_summary(self) -> UsageSummary:
        model_summaries = {}
        for model_key in self._model_call_counts:
            model_summaries[model_key] = ModelUsageSummary(
                total_calls=self._model_call_counts[model_key],
                total_input_tokens=self._model_input_tokens[model_key],
                total_output_tokens=self._model_output_tokens[model_key],
            )
        if not model_summaries:
            key = self.model or self.model_name
            model_summaries[key] = ModelUsageSummary(
                total_calls=0, total_input_tokens=0, total_output_tokens=0
            )
        return UsageSummary(model_usage_summaries=model_summaries)

    def get_last_usage(self) -> ModelUsageSummary:
        return ModelUsageSummary(
            total_calls=1,
            total_input_tokens=self._last_input_tokens,
            total_output_tokens=self._last_output_tokens,
        )
