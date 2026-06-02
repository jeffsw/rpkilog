# rpkilog — Agent Instructions

## git

### commit messages

Prefer bullet points over prose.

### pre-commit hooks

There are standard pre-commit hooks in this repository.  They can be invoked manually with: `uv run --directory python/rpkilog prek run` which is a good way to perform basic verifications after edits, too.

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
