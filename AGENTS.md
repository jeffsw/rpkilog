# rpkilog — Agent Instructions

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
