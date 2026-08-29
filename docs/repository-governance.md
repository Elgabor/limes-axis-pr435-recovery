# Repository Governance

This page is the operating map for repository maintenance. Detailed policy lives
in the linked source files so one rule has one owner.

## Sources of Truth

| Concern | Source | Enforcement |
| --- | --- | --- |
| Code responsibility | [`.github/CODEOWNERS`](../.github/CODEOWNERS) | Automatic review routing where the GitHub plan supports it |
| Pull-request evidence | [Pull-request template](../.github/PULL_REQUEST_TEMPLATE.md) | Every PR review |
| Release-bound changes | [`CHANGELOG.md`](../CHANGELOG.md) | PR checklist and release review |
| Architectural decisions | [`docs/adr`](./adr) | PR architecture-drift review |
| Current architecture | [`architecture.md`](./architecture.md) | Documentation contract tests |
| Dependency maintenance | [`.github/dependabot.yml`](../.github/dependabot.yml) | GitHub Dependabot |
| Local documentation paths | [`scripts/check_documentation_paths.py`](../scripts/check_documentation_paths.py) | `make docs-check` and CI |
| Public and sensitive support | [`SUPPORT.md`](../SUPPORT.md), [`SECURITY.md`](../SECURITY.md) | Triage policy |
| Community behavior | [`CODE_OF_CONDUCT.md`](../CODE_OF_CONDUCT.md) | Maintainer moderation |

## Pull-request Rules

Every PR must explain its outcome, verification evidence, risk and remaining
`NOT RUN` boundaries. Behavior, schema, security, migration, deployment and
supported-dependency changes update the changelog. Component, data-flow, trust-
boundary or runtime-dependency changes also update the architecture record or add
an ADR.

`make docs-check` must pass whenever documentation or governance paths change.
Normal code gates remain mandatory for affected components; the documentation
check is additive, not a substitute for lint, tests, builds or integration proof.

## Dependency-update Policy

Dependabot runs on a bounded schedule:

- npm, uv and GitHub Actions are checked weekly; Docker images and Docker
  Compose are checked monthly;
- minor and patch version updates are grouped within one ecosystem;
- security updates are grouped separately within one ecosystem;
- major updates remain individual PRs;
- each ecosystem has a small open-PR limit to prevent update floods.

Lockfiles remain part of each update PR. Maintainers verify the affected suite and
do not merge a dependency PR solely because the manifest resolves.

## Hosted Enforcement Boundary

At the 2026-08-29 baseline, GitHub returned HTTP 403 for repository rulesets and
branch protection because this is a private repository on a plan without those
features. CODEOWNERS still documents responsibility, but required code-owner
approval cannot be claimed as enforced. Re-check this boundary whenever the plan
or repository visibility changes.

SARIF publication follows the same honest boundary: it is best-effort when Code
Scanning is unavailable, while the subsequent Trivy critical-vulnerability gate
remains mandatory.
