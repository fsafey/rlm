#!/usr/bin/env python
"""
Smart Diff Summarizer - Token Optimization Pattern

Extracts structured summary from git diff instead of sending raw diff.
Reduces token consumption by 50-80% while maintaining commit message quality.

Target token reduction:
- Small commits (1-2 files): 500 → 150-250 tokens (50-70% reduction)
- Medium commits (3-5 files): 5,000 → 1,500-2,500 tokens (50-70% reduction)
- Large commits (10+ files): 50,000 → 5,000-10,000 tokens (80-90% reduction)
"""

import re
import sys

# Generated/build files to exclude (5-20% token savings)
EXCLUDED_PATTERNS = [
    # Lock files
    r"package-lock\.json$",
    r"poetry\.lock$",
    r"Pipfile\.lock$",
    r"yarn\.lock$",
    r"pnpm-lock\.yaml$",
    r"uv\.lock$",
    # Minified files
    r"\.min\.js$",
    r"\.min\.css$",
    # Build/dist directories
    r"/dist/",
    r"/build/",
    r"/\.next/",
    r"/node_modules/",
    r"/__pycache__/",
    # Python compiled
    r"\.pyc$",
    # Images (often verbose in diffs)
    r"\.svg$",
    r"\.png$",
    r"\.jpg$",
    r"\.jpeg$",
    r"\.gif$",
    r"\.ico$",
    r"\.webp$",
    # Database migrations (usually auto-generated)
    r"/migrations/\d{14}_",
    r"/supabase/migrations/",
    # Generated code
    r"\.gen\.ts$",
    r"\.gen\.js$",
    r"\.generated\.",
    r"_pb2\.py$",  # Protobuf
    r"\.pb\.go$",  # Protobuf
    # Data files (typically verbose in diffs)
    r"\.csv$",
    r"\.sql$",
]


def should_exclude_file(filepath: str) -> bool:
    """Check if file should be excluded from detailed analysis"""
    for pattern in EXCLUDED_PATTERNS:
        if re.search(pattern, filepath):
            return True
    return False


def extract_file_changes(diff_text: str) -> list[dict]:
    """
    Parse git diff into structured file-level changes

    Returns list of dicts:
    {
        'path': 'src/file.ts',
        'status': 'modified',  # or 'added', 'deleted', 'renamed'
        'additions': 42,
        'deletions': 15,
        'is_binary': False,
        'is_test': False,
        'functions_modified': ['functionName', 'ClassName.method'],
        'imports_added': ['import X from Y'],
        'imports_removed': ['import Z from W']
    }
    """
    files = []
    current_file = None

    # Split diff into file sections
    lines = diff_text.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]

        # New file section
        if line.startswith("diff --git"):
            if current_file:
                files.append(current_file)

            # Extract file paths
            match = re.match(r"diff --git a/(.*?) b/(.*)", line)
            if match:
                old_path = match.group(1)
                new_path = match.group(2)

                current_file = {
                    "path": new_path if new_path != "/dev/null" else old_path,
                    "old_path": old_path if old_path != "/dev/null" else None,
                    "status": "modified",
                    "additions": 0,
                    "deletions": 0,
                    "is_binary": False,
                    "is_test": False,
                    "functions_modified": [],
                    "imports_added": [],
                    "imports_removed": [],
                }

                # Detect test files
                if re.search(
                    r"(test|spec|__tests__|\.test\.|\.spec\.)",
                    current_file["path"],
                    re.IGNORECASE,
                ):
                    current_file["is_test"] = True

        # Detect file status
        elif line.startswith("new file mode"):
            if current_file:
                current_file["status"] = "added"
        elif line.startswith("deleted file mode"):
            if current_file:
                current_file["status"] = "deleted"
        elif line.startswith("rename from"):
            if current_file:
                current_file["status"] = "renamed"

        # Detect binary files
        elif line.startswith("Binary files"):
            if current_file:
                current_file["is_binary"] = True

        # Count additions/deletions and extract semantic info
        elif line.startswith("+") and not line.startswith("+++"):
            if current_file and not current_file["is_binary"]:
                current_file["additions"] += 1

                # Extract function definitions
                if re.search(r"^\+\s*(def|function|class|interface|const\s+\w+\s*=\s*\()", line):
                    func_match = re.search(r"(def|function|class|interface|const)\s+(\w+)", line)
                    if func_match:
                        current_file["functions_modified"].append(func_match.group(2))

                # Extract imports added
                if re.search(r"^\+\s*(import|from .* import|require\()", line):
                    import_clean = re.sub(r"^\+\s*", "", line).strip()
                    current_file["imports_added"].append(import_clean)

        elif line.startswith("-") and not line.startswith("---"):
            if current_file and not current_file["is_binary"]:
                current_file["deletions"] += 1

                # Extract imports removed
                if re.search(r"^\-\s*(import|from .* import|require\()", line):
                    import_clean = re.sub(r"^\-\s*", "", line).strip()
                    current_file["imports_removed"].append(import_clean)

        i += 1

    # Add last file
    if current_file:
        files.append(current_file)

    return files


def detect_change_patterns(files: list[dict]) -> list[str]:
    """
    Detect high-level patterns across all changes

    Returns: ['refactor: renamed functions', 'feat: added new API endpoint', ...]
    """
    patterns = []

    # Renamed files
    renamed = [f for f in files if f["status"] == "renamed"]
    if renamed:
        patterns.append(f"renamed {len(renamed)} file(s)")

    # New files
    added = [f for f in files if f["status"] == "added"]
    if added:
        patterns.append(f"added {len(added)} new file(s)")

    # Deleted files
    deleted = [f for f in files if f["status"] == "deleted"]
    if deleted:
        patterns.append(f"deleted {len(deleted)} file(s)")

    # Test changes
    test_files = [f for f in files if f["is_test"]]
    if test_files:
        test_changes = sum(f["additions"] + f["deletions"] for f in test_files)
        patterns.append(f"test updates ({test_changes} lines in {len(test_files)} file(s))")

    # Binary changes
    binary_files = [f for f in files if f["is_binary"]]
    if binary_files:
        patterns.append(f"binary file changes ({len(binary_files)} file(s))")

    # Large refactors
    large_changes = [f for f in files if f["additions"] + f["deletions"] > 100]
    if large_changes:
        patterns.append(f"large refactor in {len(large_changes)} file(s)")

    # Imports changed
    files_with_import_changes = [f for f in files if f["imports_added"] or f["imports_removed"]]
    if files_with_import_changes:
        patterns.append(f"dependency changes in {len(files_with_import_changes)} file(s)")

    return patterns


def generate_summary(diff_text: str, max_detail_lines: int = 100) -> str:
    """
    Generate structured summary of git diff

    Args:
        diff_text: Full git diff output
        max_detail_lines: Max total lines changed before switching to high-level summary

    Returns: Structured summary string optimized for Claude analysis
    """
    files = extract_file_changes(diff_text)

    if not files:
        return "No changes detected"

    total_additions = sum(f["additions"] for f in files)
    total_deletions = sum(f["deletions"] for f in files)
    total_lines = total_additions + total_deletions

    # Decide summary level based on size
    use_high_level = total_lines > max_detail_lines

    summary_parts = []

    # Header
    summary_parts.append("=== DIFF SUMMARY ===")
    summary_parts.append(f"Files changed: {len(files)}")
    summary_parts.append(f"Lines: +{total_additions} -{total_deletions} ({total_lines} total)")
    summary_parts.append("")

    # Change patterns
    patterns = detect_change_patterns(files)
    if patterns:
        summary_parts.append("Change patterns:")
        for pattern in patterns:
            summary_parts.append(f"  - {pattern}")
        summary_parts.append("")

    # File-level details
    if use_high_level:
        summary_parts.append("File changes (high-level summary):")
    else:
        summary_parts.append("File changes (detailed):")

    summary_parts.append("")

    for file_info in files:
        # Determine if excluded
        is_excluded = should_exclude_file(file_info["path"])

        # Basic file info
        status_icon = {
            "added": "+",
            "deleted": "-",
            "renamed": "~",
            "modified": "M",
        }.get(file_info["status"], "?")

        file_line = f"{status_icon} {file_info['path']}"

        if file_info["status"] == "renamed" and file_info["old_path"]:
            file_line += f" (from {file_info['old_path']})"

        if is_excluded:
            file_line += " [generated/lock file, skipped]"
            summary_parts.append(file_line)
            continue

        if file_info["is_binary"]:
            file_line += " [binary]"
            summary_parts.append(file_line)
            continue

        file_line += f" (+{file_info['additions']} -{file_info['deletions']})"
        summary_parts.append(file_line)

        # Add semantic details if not high-level
        if not use_high_level and not file_info["is_test"]:
            if file_info["functions_modified"]:
                funcs = ", ".join(file_info["functions_modified"][:5])
                if len(file_info["functions_modified"]) > 5:
                    funcs += f" +{len(file_info['functions_modified']) - 5} more"
                summary_parts.append(f"    Functions/classes: {funcs}")

            if file_info["imports_added"]:
                summary_parts.append(f"    Imports added: {len(file_info['imports_added'])}")
                for imp in file_info["imports_added"][:3]:
                    summary_parts.append(f"      + {imp}")

            if file_info["imports_removed"]:
                summary_parts.append(f"    Imports removed: {len(file_info['imports_removed'])}")

        summary_parts.append("")

    # Add note about summarization
    if use_high_level:
        summary_parts.append(f"Note: Large diff ({total_lines} lines) summarized at high level")
        summary_parts.append("Focus on change patterns and file-level impacts for commit message")

    return "\n".join(summary_parts)


def main():
    """
    Read git diff from stdin and output structured summary

    Usage:
        git diff --cached | uv run python summarize-diff.py
    """
    if sys.stdin.isatty():
        print(
            "Error: No input provided. Pipe git diff output to this script.",
            file=sys.stderr,
        )
        print(
            "Usage: git diff --cached | uv run python summarize-diff.py",
            file=sys.stderr,
        )
        sys.exit(1)

    diff_text = sys.stdin.read()

    if not diff_text.strip():
        print("No changes to summarize")
        sys.exit(0)

    summary = generate_summary(diff_text)
    print(summary)


if __name__ == "__main__":
    main()
