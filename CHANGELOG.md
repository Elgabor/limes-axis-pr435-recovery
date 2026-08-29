# Changelog

This file records notable changes to Limes Axis. It describes shipped or
release-bound behavior, not the complete commit history.

## [Unreleased]

### Added

- Repository governance baseline with code ownership, support and conduct
  policies, architecture decision records, bounded dependency updates and an
  automated documentation-path check ([#323](https://github.com/Limes-Labs/limes-axis/issues/323)).

### Changed

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
