# ADR 0001: Repository Governance Baseline

- **Status:** Accepted
- **Date:** 2026-08-29
- **Owners:** `@metaforismo`
- **Related:** [Issue #323](https://github.com/Limes-Labs/limes-axis/issues/323)

## Context

The repository already had broad CI and security contracts, but responsibility,
change records, dependency-update policy and documentation-path validation were
either absent or scattered. Hosted branch protection and repository rulesets are
not available on the current private-repository plan, so they cannot be the only
source of governance truth.

## Decision

Version the governance baseline with the code:

- `CODEOWNERS` routes review responsibility to write-enabled maintainers;
- the pull-request template records verification, architecture drift, changelog
  impact and `NOT RUN` boundaries;
- Dependabot creates bounded, per-ecosystem update groups;
- `make docs-check` validates repository-local Markdown paths in CI;
- the changelog and ADR directory preserve release and decision history;
- support, security and conduct policies route public and sensitive reports.

SARIF publication is best-effort because hosted Code Scanning is unavailable on
the current plan. The subsequent Trivy critical-vulnerability scan remains a
required job step, so failed publication cannot skip the actual security gate.

## Consequences

- Governance remains reviewable and portable with the repository.
- A single current owner is explicit rather than hidden; future write-enabled
  teams can replace area patterns without changing the policy shape.
- Code-owner approval and protected-branch enforcement remain unavailable until
  the repository plan or visibility changes. Maintainers must re-audit hosted
  rules when that happens.
- Dependency majors remain separate review events; minor and patch updates are
  grouped only within one ecosystem.

## Alternatives Considered

- **Hosted rules as the primary baseline:** rejected because the current plan
  returns HTTP 403 for rulesets and branch protection, and repository clones would
  not carry that policy.
- **One cross-ecosystem dependency group:** rejected because a single failed
  package manager would block unrelated updates and increase review blast radius.
- **A third-party governance bot:** rejected because the required controls fit
  GitHub-native files and existing CI without another trust dependency.

## Verification

- `make docs-check`
- focused documentation-checker tests
- existing CI, container-security contract and pull-request checks
- `NOT RUN`: enforced code-owner approval and protected `main`, unavailable on the
  current private-repository plan

## Supersession

None.
