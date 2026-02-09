import asyncio
import subprocess
from typing import Any

from rlm.clients.base_lm import BaseLM
from rlm.core.types import ModelUsageSummary, UsageSummary


class ClaudeCLI(BaseLM):
    """BaseLM client that shells out to `claude -p` (Claude Code CLI).

    Uses the user's authenticated Claude Code session -- no API key needed.
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
        self._call_count: int = 0

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
            "text",
            "--no-session-persistence",
            "--tools",
            self.tools,
        ]
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

    def completion(
        self, prompt: str | list[dict[str, Any]] | dict[str, Any], model: str | None = None
    ) -> str:
        prompt_text, system_prompt = self._build_prompt(prompt)
        cmd = self._build_cmd(prompt_text, system_prompt, model_override=model)

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
        if result.returncode != 0:
            raise RuntimeError(f"claude CLI failed (rc={result.returncode}): {result.stderr}")

        self._call_count += 1
        return result.stdout.strip()

    async def acompletion(
        self, prompt: str | list[dict[str, Any]] | dict[str, Any], model: str | None = None
    ) -> str:
        prompt_text, system_prompt = self._build_prompt(prompt)
        cmd = self._build_cmd(prompt_text, system_prompt, model_override=model)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)

        if proc.returncode != 0:
            raise RuntimeError(f"claude CLI failed (rc={proc.returncode}): {stderr.decode()}")

        self._call_count += 1
        return stdout.decode().strip()

    def _usage_summary(self) -> UsageSummary:
        key = self.model or self.model_name
        return UsageSummary(
            model_usage_summaries={
                key: ModelUsageSummary(
                    total_calls=self._call_count,
                    total_input_tokens=0,
                    total_output_tokens=0,
                ),
            }
        )

    def get_usage_summary(self) -> UsageSummary:
        return self._usage_summary()

    def get_last_usage(self) -> ModelUsageSummary:
        return ModelUsageSummary(
            total_calls=self._call_count,
            total_input_tokens=0,
            total_output_tokens=0,
        )
