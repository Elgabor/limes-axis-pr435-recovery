# Changelog

This file records notable changes to Limes Axis. It describes shipped or
release-bound behavior, not the complete commit history.

## [Unreleased]

### Added

- A repository-topology ADR makes the private repository the commercial source
  of truth and defines the fail-closed, fresh-history boundary for any future
  OSS edition ([#319](https://github.com/Limes-Labs/limes-axis/issues/319)).
- A machine-checked capability matrix assigns current and planned product scope
  to OSS, shared SDK, Hosted or Enterprise/private-cloud editions and blocks
  export on undecided entries
  ([#320](https://github.com/Limes-Labs/limes-axis/issues/320)).
- A compliance-readiness matrix records deployment-specific applicability,
  roles, control/evidence ownership and unresolved ISO/IEC 27001, GDPR, EU AI
  Act and NIS2 review boundaries
  ([#372](https://github.com/Limes-Labs/limes-axis/issues/372)).
- Repository governance baseline with code ownership, support and conduct
  policies, architecture decision records, bounded dependency updates and an
  automated documentation-path check ([#323](https://github.com/Limes-Labs/limes-axis/issues/323)).

### Changed

- Data-asset lineage batches promotion history reads while retaining tenant
  isolation, chronological output and the latest-50 limit per proposal.
- CSV preview detects duplicate headers in one pass with unchanged validation
  messages and ordering.
- Local development targets load the repository-root environment file; setup
  uses committed lockfiles and verification includes the public schema package.

- The architecture overview now describes current runtime truth while delivery
  history lives in a separate changelog ([#359](https://github.com/Limes-Labs/limes-axis/issues/359)).
- The API compatibility suite is warning-clean and fails on new warnings
  ([#377](https://github.com/Limes-Labs/limes-axis/issues/377)).

## Changelog Policy

Every pull request that changes user-visible behavior, public schemas, security
posture, data migrations, deployment requirements or supported dependencies must
add an entry under `Unreleased`.

Pure tests, internal refactors and documentation corrections may omit an entry
when they do not change those contracts. The pull request must state why the
change is exempt. Architecture changes additionally require an ADR or an entry in
`docs/architecture-changelog.md`.

At release time, maintainers move the relevant `Unreleased` entries into a
versioned section with an ISO date. Entries describe outcomes and compatibility
impact; commit-by-commit chronology stays in Git history.
