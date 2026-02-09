---
name: release
description: >
  Release management with changelog generation, version tagging, and GitHub releases.
  Gathers commits since last semver tag, groups by conventional commit type, suggests
  version bump. Use when user types /release or asks about versioning, changelog,
  or publishing a release.
---

# Release

Manage releases: gather changes, generate changelog, tag, publish.

## Sub-commands

### `/release` (full flow)

Run Steps 1-5 sequentially. **Step 4 requires user approval before Step 5.**

### `/release status`

Run Step 1 only. Show current version + unreleased commit summary.

### `/release changelog`

Run Steps 1-3. Generate and display changelog without tagging or publishing.

### `/release tag vX.Y.Z`

Create an annotated tag only (skip gather/changelog):

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
```

Report success. Do NOT push unless user asks.

### `/release notes <hash> key=val`

Attach a git note to a specific commit:

```bash
git notes add -f -m "key=val" <hash>
```

---

## Step 1: Gather

```bash
uv run python .claude/skills/release/scripts/gather.py
```

Outputs JSON with: current version, suggested bump, commit count, and commits grouped by type.

## Step 2: Interpret

From the JSON output, report:

```
Release Status
  Current:    vX.Y.Z (or "no semver tags")
  Unreleased: N commits since <tag>
  Suggested:  vX.Y.Z (bump reason)

  Breakdown:
    feat(N)  fix(N)  refactor(N)  chore(N)  ...
```

If `/release status` was invoked, stop here.

## Step 3: Generate Changelog

Format the grouped commits as a markdown changelog:

```markdown
## vX.Y.Z

### Features

- **scope**: description (hash)

### Fixes

- **scope**: description (hash)

### Refactoring

- description (hash)

### Maintenance

- description (hash)
```

Type-to-heading map:

| Type     | Heading       |
| -------- | ------------- |
| feat     | Features      |
| fix      | Fixes         |
| refactor | Refactoring   |
| perf     | Performance   |
| docs     | Documentation |
| chore    | Maintenance   |
| ci       | CI/CD         |
| test     | Tests         |
| style    | Style         |
| build    | Build         |
| other    | Other         |

Omit empty sections. If scope is null, skip the bold prefix.

If `/release changelog` was invoked, stop here.

## Step 4: Present for Approval

Display the changelog and suggested version to the user. Ask:

```
Ready to tag and publish vX.Y.Z? (yes / different version / no)
```

**CRITICAL**: Do NOT proceed to Step 5 without explicit user approval. If the user says no, stop. If they provide a different version, use that instead.

## Step 5: Tag and Publish

After approval:

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
gh release create vX.Y.Z --title "vX.Y.Z" --notes "CHANGELOG_CONTENT"
```

Report the release URL from `gh release create` output.
