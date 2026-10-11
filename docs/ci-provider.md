# CI provider operator

The shared registry and operator live in Standalone Search at
`config/ci-providers.json` and `scripts/ci/provider_swap.py`.
This repository's `scripts/ci-provider` forwards its Git remote identity and
all operator arguments to that entry point. Set `SEARCH_CI_REPO` when the shared
checkout is not the sibling `standalone-search` directory.

```sh
scripts/ci-provider --help
scripts/ci-provider
scripts/ci-provider --to github
scripts/ci-provider --to cloudbuild
```

No `--to` selects the registry's preferred provider, Codex. The default operation
is a read-only plan. GitHub Actions and Google Cloud Build remain selectable
secondary providers; selection does not establish qualification or activation.
The registry declares this repository inventory-only. An activation attempt must
fail until an accepted full workload and native provider adapter exist. A plan
can read live repository gates; these local files do not prove live required-check
settings or successful provider execution.

## Existing workload boundary

Current source workflow: Test and Style. `test` on Python 3.11 and 3.12, plus `lint` (Ruff check/format and advisory ty check). Tests exclude Modal and client integration suites as the current workflow specifies.
The existing GitHub Actions workflows remain intact and own execution until a
replacement is qualified against the exact workload and required checks.

Separate operations: GitHub Pages documentation publishing and PyPI releases. Provider planning does not authorize or migrate
these operations.

## Deterministic portable workload

`config/ci-workload.json` declares the existing workflow commands, and
`scripts/ci-cloud` delegates to the shared `scripts/ci/portable_codex_job.py`.
It runs all portable scopes, records real exits and logs, and exports
`CI_OUTPUT_DIR/result.json`. This is candidate workload evidence with
`app_bound_proof=false`; provider-native publication and acceptance remain
separate coordinator requirements.

The external supervisor must set `CI_PROVIDER=codex`, `CODEX_CI_RUN_ID`,
`CI_EVENT=push|pull_request`, `CI_EVENT_HEAD` (full SHA), `CI_EVENT_BRANCH`,
and a new absolute `CI_OUTPUT_DIR` outside the tested checkout. For pull requests,
set `CI_BASE_SHA`, positive `CI_PR`, and `CI_DRAFT=false`; the clean checkout must
be the exact base/head merge, with both its parents and merged tree verified.
Push checkouts must match the exact event head. The runner requires native Linux,
Bash, uv, and the workload's declared toolchain. A source mismatch, missing tool,
failed command, timeout or interruption produces a nonzero result.

```sh
# Run only from the supervisor-prepared clean source and environment.
SEARCH_CI_REPO=/path/to/reviewed/standalone-search scripts/ci-cloud
```

The two test matrix entries use separate locked project environments for Python 3.11 and 3.12. Both execute the existing test exclusions and coverage flags. Style uses the existing Ruff and ty versions; ty remains advisory. The runner does not run excluded external-provider suites, publish to PyPI or deploy documentation.
