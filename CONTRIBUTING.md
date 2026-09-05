# Contributing to Limes Axis

Limes Axis is early. Contributions by authorized collaborators should improve
clarity, architecture, tests, documentation or implementation without weakening
the core principles.

## Principles

- Keep the commercial product self-hostable; future OSS disposition is decided
  separately by the edition matrix.
- Avoid required managed-service dependencies.
- Treat security, tenant isolation, permissions and audit as product features.
- Prefer typed schemas and explicit interfaces over implicit coupling.
- Keep public documentation public-safe.
- Do not add application code without tests and documented acceptance criteria.

## Contributor License Agreement

Limes Axis intends to require a Contributor License Agreement before accepting
substantial external contributions.

See [`CLA.md`](./CLA.md).

The CLA process is lightweight at repository launch and should receive legal
review before broad external contribution intake.

## Development Status

Axis is under active development. Use the repository `Makefile` and package-local
commands documented in the README; do not infer readiness from one component's
tests alone.

The [development guide](docs/development.md) lists targeted checks, local CI
parity, worktree setup and runtime/browser debugging. Repository-local agent
instructions are in [AGENTS.md](AGENTS.md).

## Pull Request Expectations

- open a pull request against `main`;
- describe the change and why it matters;
- include tests for behavior changes;
- update docs when public behavior changes;
- update `CHANGELOG.md` for release-bound behavior, schema, security, migration,
  deployment or supported-dependency changes;
- add an ADR for component ownership, data-flow, trust-boundary, runtime-
  dependency or repository-wide policy decisions;
- keep changes scoped;
- avoid unrelated refactors;
- run `make docs-check` when documentation or governance paths change;
- list relevant verification and every remaining `NOT RUN` boundary;
- include security implications for auth, permissions, tenant isolation, agents,
  workflows, connectors, model routing or data egress changes.

## Reporting Security Issues

Do not open a public issue for sensitive vulnerabilities. Follow
[`SECURITY.md`](./SECURITY.md) and use GitHub private vulnerability reporting when
available.
