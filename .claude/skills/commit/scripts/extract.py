#!/usr/bin/env python
"""
Git Context Extraction (Deterministic)

Extracts git state and outputs structured context for commit message generation.
Parallel git operations save 150-300ms per commit.
"""

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def run_command(cmd, check=True):
    """Run shell command and return output"""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        print(f"Error: {result.stderr}", file=sys.stderr)
        sys.exit(result.returncode)
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def get_session_id():
    """Extract current Claude Code session ID deterministically"""
    project_dir = Path.cwd()

    # Convert absolute path to Claude project dir format (slashes become dashes)
    claude_project_dir = str(project_dir).replace("/", "-")
    claude_dir = Path.home() / ".claude" / "projects" / claude_project_dir

    if not claude_dir.exists():
        return "no-session-id"

    # Find most recent .jsonl file
    jsonl_files = sorted(claude_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)

    if not jsonl_files:
        return "no-session-id"

    return jsonl_files[0].stem


def get_git_status():
    """Get list of changed files"""
    stdout, _, _ = run_command("git status --short")
    return stdout if stdout else "No changes"


def stage_tracked_changes():
    """Stage tracked file changes only (safe — won't add .env or untracked files)"""
    run_command("git add -u")


def get_git_diff():
    """Get diff of staged changes (call stage_all_changes first)"""
    stdout, _, _ = run_command("git diff --cached --no-color")

    if not stdout:
        return "No changes to commit"

    return stdout


def get_recent_commits():
    """Get recent commit messages for style consistency"""
    stdout, _, _ = run_command("git log -5 --pretty=format:'%s' 2>/dev/null")
    return stdout if stdout else "No recent commits"


def summarize_diff(diff: str) -> str:
    """
    Use summarize-diff.py to generate structured diff summary

    Token optimization: Structured summary is 50-80% smaller than raw diff
    while maintaining semantic information needed for commit messages.
    """
    script_dir = Path(__file__).parent
    summarizer_path = script_dir / "summarize-diff.py"

    result = subprocess.run(
        ["uv", "run", "python", str(summarizer_path)],
        input=diff,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        # Fallback to truncated diff if summarizer fails
        print(
            f"Summarizer failed, using truncated diff: {result.stderr}",
            file=sys.stderr,
        )
        return truncate_diff_fallback(diff)

    return result.stdout


def truncate_diff_fallback(diff, max_lines=500):
    """Fallback: Truncate diff if summarizer fails"""
    lines = diff.split("\n")
    if len(lines) <= max_lines:
        return diff

    truncated = "\n".join(lines[:max_lines])
    return f"{truncated}\n\n... (diff truncated, {len(lines) - max_lines} more lines)"


def main():
    """Extract git context for commit message generation"""
    # Stage tracked changes (safe — won't add .env or untracked files)
    stage_tracked_changes()

    # Extract git state in parallel (150-300ms savings)
    with ThreadPoolExecutor(max_workers=3) as executor:
        status_future = executor.submit(get_git_status)
        diff_future = executor.submit(get_git_diff)
        commits_future = executor.submit(get_recent_commits)

        git_status = status_future.result()
        git_diff = diff_future.result()
        recent_commits = commits_future.result()

    session_id = get_session_id()

    if git_diff == "No changes to commit":
        print("No changes to commit")
        sys.exit(0)

    # Generate structured diff summary (token optimization)
    diff_summary = summarize_diff(git_diff)

    # Check for untracked files that need explicit staging
    untracked_stdout, _, _ = run_command("git ls-files --others --exclude-standard", check=False)
    untracked = [f for f in untracked_stdout.split("\n") if f.strip()] if untracked_stdout else []

    # Output context for Claude to generate commit message
    print("### Changed Files")
    print("```")
    print(git_status)
    print("```")

    if untracked:
        print("\n### Untracked Files (not staged — add explicitly if needed)")
        print("```")
        for f in untracked:
            print(f"  ?? {f}")
        print("```")

    print("\n### Diff Summary")
    print("```")
    print(diff_summary)
    print("```")

    print("\n### Recent Commits (style reference)")
    print("```")
    print(recent_commits)
    print("```")

    print(f"\n### Session ID: {session_id}")


if __name__ == "__main__":
    main()
