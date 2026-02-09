#!/usr/bin/env python
"""
Release Changelog Gatherer (Deterministic)

Finds the latest semver tag, collects commits since then,
groups by conventional commit type, suggests version bump.
Outputs structured JSON for Claude to format into changelog.
"""

import json
import re
import subprocess
import sys

SEMVER_TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")

COMMIT_RE = re.compile(
    r"^(?P<type>[a-z]+)" r"(?:\((?P<scope>[^)]+)\))?" r"(?P<breaking>!)?" r":\s*(?P<subject>.+)$"
)

TYPE_ORDER = ["feat", "fix", "refactor", "perf", "docs", "chore", "ci", "test", "style", "build"]


def run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def find_latest_semver_tag() -> str | None:
    """Find the latest semver tag (vX.Y.Z only, no suffixes)."""
    raw = run_git("tag", "--list", "--sort=-version:refname")
    if not raw:
        return None

    for tag in raw.splitlines():
        tag = tag.strip()
        if SEMVER_TAG_RE.match(tag):
            return tag

    return None


def get_commits_since(tag: str | None) -> list[dict]:
    """Get commits since tag (or all commits if no tag)."""
    fmt = "%H%x00%h%x00%an%x00%s"

    if tag:
        raw = run_git("log", f"{tag}..HEAD", f"--format={fmt}")
    else:
        raw = run_git("log", f"--format={fmt}")

    if not raw:
        return []

    commits = []
    for line in raw.splitlines():
        parts = line.split("\x00")
        if len(parts) != 4:
            continue
        full_hash, short_hash, author, subject = parts
        commits.append(
            {
                "hash": full_hash,
                "short_hash": short_hash,
                "author": author,
                "subject": subject,
            }
        )

    return commits


def parse_commit(commit: dict) -> dict:
    """Parse conventional commit prefix from subject."""
    match = COMMIT_RE.match(commit["subject"])
    if match:
        commit["type"] = match.group("type")
        commit["scope"] = match.group("scope")
        commit["breaking"] = match.group("breaking") == "!"
        commit["description"] = match.group("subject")
    else:
        commit["type"] = "other"
        commit["scope"] = None
        commit["breaking"] = False
        commit["description"] = commit["subject"]

    # Also detect BREAKING CHANGE in subject text
    if "BREAKING CHANGE" in commit["subject"].upper():
        commit["breaking"] = True

    return commit


def group_commits(commits: list[dict]) -> dict[str, list[dict]]:
    """Group parsed commits by type, preserving order."""
    groups: dict[str, list[dict]] = {}
    for commit in commits:
        t = commit["type"]
        if t not in groups:
            groups[t] = []
        groups[t].append(commit)

    # Sort groups by TYPE_ORDER, unknown types at end
    ordered: dict[str, list[dict]] = {}
    for t in TYPE_ORDER:
        if t in groups:
            ordered[t] = groups.pop(t)
    # Remaining types (other, merge, etc.)
    for t in sorted(groups.keys()):
        ordered[t] = groups[t]

    return ordered


def suggest_bump(current: str | None, commits: list[dict]) -> dict:
    """Suggest version bump based on commit types."""
    has_breaking = any(c.get("breaking") for c in commits)
    has_feat = any(c.get("type") == "feat" for c in commits)

    if current and SEMVER_TAG_RE.match(current):
        m = SEMVER_TAG_RE.match(current)
        major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        major, minor, patch = 0, 0, 0

    if has_breaking:
        bump = "major"
        suggested = f"v{major + 1}.0.0"
    elif has_feat:
        bump = "minor"
        suggested = f"v{major}.{minor + 1}.0"
    else:
        bump = "patch"
        suggested = f"v{major}.{minor}.{patch + 1}"

    return {
        "bump": bump,
        "suggested_version": suggested,
        "reason": (
            "breaking change detected"
            if has_breaking
            else "new feature(s)"
            if has_feat
            else "fixes and maintenance"
        ),
    }


def main():
    tag = find_latest_semver_tag()
    commits = get_commits_since(tag)
    parsed = [parse_commit(c) for c in commits]
    groups = group_commits(parsed)
    bump = suggest_bump(tag, parsed)

    output = {
        "current_version": tag,
        "suggested_version": bump["suggested_version"],
        "bump": bump["bump"],
        "bump_reason": bump["reason"],
        "commit_count": len(parsed),
        "since": tag or "(beginning of history)",
        "groups": {
            t: [
                {
                    "short_hash": c["short_hash"],
                    "scope": c["scope"],
                    "description": c["description"],
                    "breaking": c["breaking"],
                    "author": c["author"],
                }
                for c in commits_in_group
            ]
            for t, commits_in_group in groups.items()
        },
    }

    json.dump(output, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
