#!/usr/bin/env python
"""
Git Commit Execution (Deterministic)

Reads commit message from stdin, writes to auto-cleaned tempfile,
executes git commit -F. No persistent files between invocations.

Supports --dry-run flag for preview without committing.
"""

import subprocess
import sys
import tempfile
from pathlib import Path


def execute_commit(msg_file: Path, retry_count=0):
    """
    Execute git commit -F <file>.

    Handles pre-commit hook file modifications by re-staging and retrying once.
    """
    result = subprocess.run(
        f"git commit -F '{msg_file}'",
        shell=True,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        # Check if pre-commit hooks modified files (common with prettier, ruff, etc.)
        modified = subprocess.run(
            "git diff --name-only",
            shell=True,
            capture_output=True,
            text=True,
            check=False,
        )
        modified_files = [f for f in modified.stdout.strip().split("\n") if f.strip()]

        if modified_files and retry_count < 1:
            print(
                f"Pre-commit hooks modified {len(modified_files)} file(s), re-staging...",
                file=sys.stderr,
            )
            for f in modified_files[:5]:
                print(f"   {f}", file=sys.stderr)
            subprocess.run("git add -u", shell=True, check=False)
            return execute_commit(msg_file, retry_count + 1)

        print(f"Commit failed: {result.stderr}", file=sys.stderr)
        sys.exit(result.returncode)

    return result.stdout.strip()


def main():
    dry_run = "--dry-run" in sys.argv

    # Read commit message from stdin (piped via HEREDOC)
    if sys.stdin.isatty():
        print("Error: Pipe commit message via stdin", file=sys.stderr)
        print("Usage: echo 'message' | uv run python execute.py", file=sys.stderr)
        sys.exit(1)

    commit_message = sys.stdin.read().strip()
    if not commit_message:
        print("Error: Empty commit message", file=sys.stderr)
        sys.exit(1)

    if dry_run:
        print("DRY RUN - Preview only, no commit created")
        print("=" * 60)
        print(commit_message)
        print("=" * 60)
        sys.exit(0)

    # Write to auto-cleaned tempfile (unique per invocation, no collisions)
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    tmp_path = Path(tmp.name)
    try:
        tmp.write(commit_message)
        tmp.close()
        result = execute_commit(tmp_path)
        print(result)
        print("Commit created successfully!")
        if "Session:" in commit_message:
            session_id = commit_message.split("Session:")[-1].strip().split()[0]
            print(f"Resume later with: claude --resume {session_id}")
    finally:
        tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
