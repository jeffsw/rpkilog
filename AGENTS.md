# rpkilog — Agent Instructions

## git

### commit messages

Prefer bullet points over prose.

### pre-commit hooks

Standard pre-commit hooks run via `prek` — see [Verification](#verification). `prek run --all-files`
is the normal invocation: the repo's trailing newlines are normalized, so it no longer churns
unrelated files. `prek` is on `PATH` via the project venv, so plain `prek run` works (no
`uv run --directory …` wrapper needed).

## Verification

Verification is defined once as **mise tasks** (`.mise/tasks/`), so the same checks run for Claude,
in pre-commit hooks, on developer CLIs, and in GitHub CI. The terraform/atlas versions the tasks
use are pinned in `.mise.toml`.

- `mise run verify` — everything: terraform + all pre-commit hooks + python lint & fast tests.
- `mise run verify-tf` — `terraform fmt -check` + `init -backend=false` + `validate` for every
  root and module under `terraform/`.
- `mise run verify-hooks` — all `prek` (pre-commit) hooks on all files.
- `mise run verify-py` — flake8 (`mise run lint`) + fast tests (`mise run test-fast`).
- `mise run fmt` — auto-format (`terraform fmt -recursive`, writes changes).
- `mise run migrate-hash` — re-hash atlas migration dirs (writes `migrations/atlas.sum`); another
  auto-fixer, sibling to `fmt`.
- `mise run test` — full pytest; `mise run test-fast` skips slow tests.

The four contexts, all sharing those definitions:

1. **Claude / humans** run `mise run verify` (or a narrower `verify-*` / `lint` / `test` task).
   These are allow-listed in the committed `.claude/settings.json`, so Claude runs them without a
   permission prompt. The `lint` task is the single source of truth for the flake8 file set.
2. **pre-commit / git** — `prek` runs the file-hygiene hooks plus a `terraform-verify` local hook
   that calls `mise run verify-tf`, and an `atlas-migrate-hash` local hook that calls
   `mise run migrate-hash`. The latter auto-fixes a stale `migrations/atlas.sum`: if a migration
   `*.sql` was edited without re-hashing, the hook rewrites `atlas.sum` and the commit aborts —
   re-stage and re-commit. (Otherwise the mismatch only surfaces later at `atlas migrate apply`.)
3. **GitHub CI** — the `verify` job runs `mise run verify-hooks` + `mise run lint`; the pytest
   matrix runs `mise run test` / `test-fast`.

After a set of changes, Claude should run `mise run verify` on its own initiative — it is
allow-listed in `.claude/settings.json` (`Bash(mise run verify*)`), so it runs without a
permission prompt and needs no approval. Don't ask the user which verification to run; just run
`mise run verify` (or a scoped `verify-*` task when only one area changed) and report the result.

## Python

### Style Guide

#### Line Length

Assume co-authors have their IDEs configured with line-length rulers at 100 and 120 characters.
100 characters is considered our soft limit, breaking the line after 100 characters.  120 is
our hard limit.

#### Comprehensions

Strongly prefer traditional C-style loops over list comprehensions or dict comprehensions.

#### Returning from Functions

When returning from a function, always store the return value in a variable within the function scope
before returning.  This makes it easier to set a debugger breakpoint condition.  If in doubt about the
name for a variable used to hold the return value, `retval`, `retstr`, `retlist`, or `retdict` are 
alright default choices.

#### Enums

Use Docstrings on Enum members to describe the values.

### Testing

The golden file `test_data/rpkiclient_summary_20250720T100145Z.json.bz2` has an internal
`metadata.buildtime` of `20250720T100143Z` — two seconds earlier than the `100145Z` in its filename.
Code that derives a filename/S3 key from the JSON buildtime (e.g. `rpkiclient_uploader.s3_upload` via
`SnapshotSummaryFile.datetimestamp_from_json()`) therefore produces a `100143Z` key, not `100145Z`.
Tests that assert against such a key should compute it from the JSON buildtime, not the filename.

## Reviewing PRs or branches

When identifying issues or suggesting changes, prefer markdown checkboxes instead of bullet points.  For
non-actionable review comments, bullet points are fine.

If reviewing changes locally, offer to create a temporary file in the repo root named REVIEW.md for organizing
the review results and remediations.

## Terraform

This project uses **HashiCorp Terraform** (not OpenTofu).

### README.md files for terraform modules

Don't write README.md files which primarily repeat the variables or outputs of a module.
It may be appropriate to explain modules with a concise mermaid flowchart of the major
resources.  An example of how to use a module is also good.  We don't need to put information
in README.md which can easily be found in the `description` of variables or even inferred
from the names & types of variables.

We don't include changelogs in module README.md.

### output blocks

The `type` argument on `output` blocks is supported from Terraform 1.15 onward.  Any module
that uses it should declare `required_version = ">= 1.15"` in its `terraform {}` block.
The `type` argument accepts any valid [type constraint expression](https://developer.hashicorp.com/terraform/language/expressions/type-constraints)
(primitive types `string`, `number`, `bool`; collection types `list(…)`, `map(…)`, `set(…)`;
and structural types `object({…})`, `tuple([…])`).  It is optional — omitting it allows any
type — but adding it to module outputs improves validation and documentation for callers.

## WWW UI

The site UI (`www/`) uses a BBS / green-screen terminal design system.

- Before making any UI changes, invoke the `rpkilog-design` skill. It loads design guidelines, color tokens, component patterns, and copy rules.
- Design system component changes (colors, borders, spacing on `rk-*` classes) belong in `www/styles.css`. Do **not** add overrides in `www/rpkilog.css` — that file is for site-specific concerns only (JS-generated table markup, pagination spans, loading animation).
- See the **WWW UI** section of `DEVNOTES.md` for an explanation of the three CSS files and how they layer.
