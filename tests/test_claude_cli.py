"""Tests for ClaudeCLI client."""

import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rlm.clients.claude_cli import ClaudeCLI


def _successful_run(*args, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=args[0] if args else [],
        returncode=0,
        stdout="test response",
        stderr="",
    )


def _failed_run(*args, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=args[0] if args else [],
        returncode=1,
        stdout="",
        stderr="something went wrong",
    )


# -- Base command flags --


@patch("subprocess.run", side_effect=_successful_run)
def test_default_cmd(mock_run: MagicMock) -> None:
    """Default params produce correct cmd: tools disabled, no-session-persistence, text output."""
    client = ClaudeCLI()
    client.completion("hello")

    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "claude"
    assert cmd[1:3] == ["-p", "hello"]
    assert "--output-format" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "text"
    assert "--no-session-persistence" in cmd
    assert "--tools" in cmd
    assert cmd[cmd.index("--tools") + 1] == ""


# -- Per-flag tests --


@patch("subprocess.run", side_effect=_successful_run)
def test_model_flag(mock_run: MagicMock) -> None:
    """Setting model='opus' adds --model opus to cmd."""
    client = ClaudeCLI(model="opus")
    client.completion("hello")

    cmd = mock_run.call_args[0][0]
    idx = cmd.index("--model")
    assert cmd[idx + 1] == "opus"


@patch("subprocess.run", side_effect=_successful_run)
def test_model_override_per_call(mock_run: MagicMock) -> None:
    """Per-call model override takes precedence over constructor model."""
    client = ClaudeCLI(model="sonnet")
    client.completion("hello", model="opus")

    cmd = mock_run.call_args[0][0]
    idx = cmd.index("--model")
    assert cmd[idx + 1] == "opus"


@patch("subprocess.run", side_effect=_successful_run)
def test_max_budget(mock_run: MagicMock) -> None:
    """Setting max_budget_usd=0.50 adds --max-budget-usd 0.5."""
    client = ClaudeCLI(max_budget_usd=0.50)
    client.completion("hello")

    cmd = mock_run.call_args[0][0]
    idx = cmd.index("--max-budget-usd")
    assert cmd[idx + 1] == "0.5"


@patch("subprocess.run", side_effect=_successful_run)
def test_permission_mode(mock_run: MagicMock) -> None:
    """Setting permission_mode='bypassPermissions' adds the flag."""
    client = ClaudeCLI(permission_mode="bypassPermissions")
    client.completion("hello")

    cmd = mock_run.call_args[0][0]
    idx = cmd.index("--permission-mode")
    assert cmd[idx + 1] == "bypassPermissions"


@patch("subprocess.run", side_effect=_successful_run)
def test_allowed_tools(mock_run: MagicMock) -> None:
    """Setting allowed_tools=['Bash', 'Read'] adds --allowedTools Bash --allowedTools Read."""
    client = ClaudeCLI(allowed_tools=["Bash", "Read"])
    client.completion("hello")

    cmd = mock_run.call_args[0][0]
    # Collect all --allowedTools values
    tool_values = []
    for i, token in enumerate(cmd):
        if token == "--allowedTools":
            tool_values.append(cmd[i + 1])
    assert tool_values == ["Bash", "Read"]


@patch("subprocess.run", side_effect=_successful_run)
def test_extra_flags(mock_run: MagicMock) -> None:
    """Setting extra_flags=['--verbose'] appends to cmd."""
    client = ClaudeCLI(extra_flags=["--verbose"])
    client.completion("hello")

    cmd = mock_run.call_args[0][0]
    assert "--verbose" in cmd


# -- Prompt handling --


@patch("subprocess.run", side_effect=_successful_run)
def test_system_prompt_extraction(mock_run: MagicMock) -> None:
    """Chat messages with system role extract correctly."""
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hi there"},
    ]
    client = ClaudeCLI()
    client.completion(messages)

    cmd = mock_run.call_args[0][0]
    idx = cmd.index("--system-prompt")
    assert cmd[idx + 1] == "You are helpful."
    # The prompt text should contain the user message but not the system message
    prompt_text = cmd[2]  # -p <prompt_text>
    assert "Hi there" in prompt_text
    assert "You are helpful" not in prompt_text


# -- Timeout --


@patch("subprocess.run", side_effect=_successful_run)
def test_timeout_configurable(mock_run: MagicMock) -> None:
    """Custom timeout is used in subprocess call."""
    client = ClaudeCLI(timeout=60)
    client.completion("hello")

    assert mock_run.call_args[1]["timeout"] == 60


# -- Error handling --


@patch("subprocess.run", side_effect=_failed_run)
def test_completion_error_handling(mock_run: MagicMock) -> None:
    """Non-zero return code raises RuntimeError."""
    client = ClaudeCLI()
    with pytest.raises(RuntimeError, match="claude CLI failed"):
        client.completion("hello")


# -- Usage summary key --


def test_usage_summary_uses_model_name() -> None:
    """Default usage summary key is model_name."""
    client = ClaudeCLI()
    summary = client.get_usage_summary()
    assert "claude-cli" in summary.model_usage_summaries


def test_usage_summary_uses_model_when_set() -> None:
    """When model is set, usage summary key uses model instead of model_name."""
    client = ClaudeCLI(model="opus")
    summary = client.get_usage_summary()
    assert "opus" in summary.model_usage_summaries
    assert "claude-cli" not in summary.model_usage_summaries


# -- _build_cmd unit tests --


def test_build_cmd_no_system_prompt() -> None:
    """_build_cmd without system prompt omits --system-prompt."""
    client = ClaudeCLI()
    cmd = client._build_cmd("test", None)
    assert "--system-prompt" not in cmd


def test_build_cmd_with_system_prompt() -> None:
    """_build_cmd with system prompt includes --system-prompt."""
    client = ClaudeCLI()
    cmd = client._build_cmd("test", "be helpful")
    idx = cmd.index("--system-prompt")
    assert cmd[idx + 1] == "be helpful"


# -- Async (acompletion) --


async def _async_passthrough(coro, timeout):
    """Passthrough for asyncio.wait_for that actually awaits the coroutine."""
    return await coro


@pytest.mark.asyncio
async def test_acompletion_success() -> None:
    """acompletion returns decoded stdout on success."""
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"async response", b"")

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        with patch("asyncio.wait_for", side_effect=_async_passthrough):
            client = ClaudeCLI(model="opus", timeout=120)
            result = await client.acompletion("hello")

    assert result == "async response"
    cmd = mock_exec.call_args[0]
    assert cmd[0] == "claude"
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "opus"


@pytest.mark.asyncio
async def test_acompletion_error() -> None:
    """acompletion raises RuntimeError on non-zero exit."""
    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    mock_proc.communicate.return_value = (b"", b"async error")

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with patch("asyncio.wait_for", side_effect=_async_passthrough):
            client = ClaudeCLI()
            with pytest.raises(RuntimeError, match="claude CLI failed"):
                await client.acompletion("hello")


@pytest.mark.asyncio
async def test_acompletion_model_override() -> None:
    """acompletion per-call model override works."""
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"ok", b"")

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        with patch("asyncio.wait_for", side_effect=_async_passthrough):
            client = ClaudeCLI(model="sonnet")
            await client.acompletion("hello", model="opus")

    cmd = mock_exec.call_args[0]
    assert cmd[cmd.index("--model") + 1] == "opus"
