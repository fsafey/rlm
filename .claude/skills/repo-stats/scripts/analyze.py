#!/usr/bin/env python
"""
Repo Stats Analyzer (Deterministic)

Parses git log/diff for commit metadata, conventional commit distribution,
layer activity, hotspot files, velocity, and tag inventory.
Outputs formatted report to stdout. Stdlib only.
"""

import argparse
import re
import subprocess
from collections import Counter
from datetime import datetime

LAYER_MAP = [
    ("rlm/core/", "Core Engine"),
    ("rlm/clients/", "LM Clients"),
    ("rlm/environments/", "Environments"),
    ("rlm/utils/", "Utils"),
    ("rlm/logger/", "Logger"),
    ("tests/", "Tests"),
    ("visualizer/", "Visualizer"),
    ("examples/", "Examples"),
    ("docs/", "Docs"),
    (".claude/", "Tooling"),
]

COMMIT_TYPE_RE = re.compile(r"^(\w+)(?:\(.+?\))?!?:\s")

COMMIT_SEP = "---COMMIT---"
FIELD_SEP = "|||"


def run(cmd: list[str], **kwargs) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False, **kwargs)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def parse_range(args: argparse.Namespace) -> list[str]:
    """Build git log range args from parsed arguments."""
    if args.since_tag:
        return [f"{args.since_tag}..HEAD"]
    if args.since_days:
        return [f"--since={args.since_days} days ago"]
    return [f"-{args.count}"]


def get_commits(range_args: list[str]) -> list[dict]:
    """Parse git log for commit metadata."""
    fmt = FIELD_SEP.join(["%H", "%h", "%an", "%aI", "%s"])
    raw = run(
        ["git", "log", f"--format={COMMIT_SEP}{fmt}"] + range_args,
    )
    if not raw:
        return []

    commits = []
    for block in raw.split(COMMIT_SEP):
        block = block.strip()
        if not block:
            continue
        parts = block.split(FIELD_SEP)
        if len(parts) < 5:
            continue
        commits.append(
            {
                "hash": parts[0],
                "short": parts[1],
                "author": parts[2],
                "date": parts[3],
                "subject": parts[4].split("\n")[0],
            }
        )
    return commits


def get_files_changed(commit_hash: str) -> list[str]:
    """Get list of files changed in a commit."""
    raw = run(
        ["git", "diff-tree", "--no-commit-id", "-r", "--name-only", commit_hash],
    )
    if not raw:
        return []
    return [f for f in raw.split("\n") if f.strip()]


def classify_type(subject: str) -> str:
    """Extract conventional commit type."""
    m = COMMIT_TYPE_RE.match(subject)
    if m:
        return m.group(1).lower()
    return "other"


def classify_layer(filepath: str) -> str:
    """Map file path to project layer."""
    for prefix, label in LAYER_MAP:
        if filepath.startswith(prefix):
            return label
    return "Root/Other"


def ascii_bar(count: int, max_count: int, width: int = 30) -> str:
    """Render an ASCII bar."""
    if max_count == 0:
        return ""
    filled = round(count / max_count * width)
    return "#" * filled


def format_section(title: str) -> str:
    return f"\n{'=' * 60}\n  {title}\n{'=' * 60}"


def analyze(commits: list[dict]) -> str:
    """Build full analysis report."""
    if not commits:
        return "No commits found in the specified range."

    lines: list[str] = []
    n = len(commits)

    # -- Header --
    newest = commits[0]["date"][:10]
    oldest = commits[-1]["date"][:10]
    lines.append(format_section(f"Repo Stats: {n} commits ({oldest} .. {newest})"))

    # -- Commit type distribution --
    type_counts: Counter = Counter()
    for c in commits:
        type_counts[classify_type(c["subject"])] += 1

    lines.append(format_section("Commit Type Distribution"))
    max_ct = max(type_counts.values()) if type_counts else 0
    for ctype, count in type_counts.most_common():
        bar = ascii_bar(count, max_ct)
        pct = count / n * 100
        lines.append(f"  {ctype:<12} {bar}  {count:>3} ({pct:4.1f}%)")

    # -- Layer activity --
    layer_counts: Counter = Counter()
    file_counts: Counter = Counter()

    for c in commits:
        files = get_files_changed(c["hash"])
        seen_layers = set()
        for f in files:
            file_counts[f] += 1
            layer = classify_layer(f)
            if layer not in seen_layers:
                layer_counts[layer] += 1
                seen_layers.add(layer)

    lines.append(format_section("Layer Activity (commits touching layer)"))
    max_lc = max(layer_counts.values()) if layer_counts else 0
    for layer, count in layer_counts.most_common():
        bar = ascii_bar(count, max_lc, 25)
        pct = count / n * 100
        lines.append(f"  {layer:<18} {bar}  {count:>3} ({pct:4.1f}%)")

    # -- Hotspot files --
    lines.append(format_section("Hotspot Files (most frequently changed)"))
    top_files = file_counts.most_common(15)
    if top_files:
        max_fc = top_files[0][1]
        for filepath, count in top_files:
            bar = ascii_bar(count, max_fc, 20)
            lines.append(f"  {count:>3}x  {bar}  {filepath}")
    else:
        lines.append("  No file-level data available.")

    # -- Author distribution --
    author_counts: Counter = Counter()
    for c in commits:
        author_counts[c["author"]] += 1

    if len(author_counts) > 1:
        lines.append(format_section("Author Distribution"))
        for author, count in author_counts.most_common():
            pct = count / n * 100
            lines.append(f"  {author:<30} {count:>3} ({pct:4.1f}%)")

    # -- Commit velocity --
    dates = []
    for c in commits:
        try:
            dt = datetime.fromisoformat(c["date"])
            dates.append(dt)
        except ValueError:
            pass

    lines.append(format_section("Commit Velocity"))
    if len(dates) >= 2:
        span = (max(dates) - min(dates)).days or 1
        velocity = n / span
        lines.append(f"  Period:     {span} days")
        lines.append(f"  Velocity:   {velocity:.1f} commits/day")

        day_counts: Counter = Counter()
        for dt in dates:
            day_counts[dt.strftime("%A")] += 1
        busiest = day_counts.most_common(1)[0]
        lines.append(f"  Busiest:    {busiest[0]} ({busiest[1]} commits)")
    else:
        lines.append("  Not enough data for velocity calculation.")

    # -- Tag inventory --
    tags_raw = run(
        ["git", "tag", "--sort=-creatordate"],
    )
    lines.append(format_section("Tag Inventory"))
    if tags_raw:
        tags = [t.strip() for t in tags_raw.split("\n") if t.strip()]
        semver_re = re.compile(r"^v?\d+\.\d+")
        semver = [t for t in tags if semver_re.match(t)]
        adhoc = [t for t in tags if not semver_re.match(t)]

        lines.append(f"  Total:      {len(tags)}")
        lines.append(f"  Semver:     {len(semver)}")
        if semver:
            lines.append(f"    Latest:   {semver[0]}")
            if len(semver) > 1:
                lines.append(f"    Previous: {', '.join(semver[1:5])}")
        lines.append(f"  Ad-hoc:     {len(adhoc)}")
        if adhoc:
            lines.append(f"    Examples:  {', '.join(adhoc[:5])}")
    else:
        lines.append("  No tags found.")

    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Analyze git repo statistics")
    parser.add_argument(
        "-n",
        "--count",
        type=int,
        default=50,
        help="Number of recent commits to analyze (default: 50)",
    )
    parser.add_argument(
        "--since-tag",
        type=str,
        default=None,
        help="Analyze commits since this tag (e.g., v0.21.0)",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=None,
        help="Analyze commits from the last N days",
    )
    args = parser.parse_args()

    range_args = parse_range(args)
    commits = get_commits(range_args)
    report = analyze(commits)
    print(report)


if __name__ == "__main__":
    main()
