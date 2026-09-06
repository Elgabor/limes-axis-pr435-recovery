# ADR 0013: OSS Candidate Provenance Gate

- **Status:** Accepted
- **Date:** 2026-09-07
- **Owners:** `@metaforismo`
- **Related:** [Issue #321](https://github.com/Limes-Labs/limes-axis/issues/321),
  [ADR 0002](0002-commercial-source-and-oss-export-boundary.md)

## Context

The accepted commercial/OSS topology requires reproducible, files-only staging
and explicit release approvals. The edition matrix classifies capabilities but
its overlapping areas cannot select safe source files. There is no reviewed
production export list or legal clearance to publish the product.

## Decision

A repository-owned, offline Python generator prepares a private candidate from
a clean checkout at an immutable commit. A committed exact-file JSON allowlist
pins the matrix and each file's digest, capability mapping, licence declaration
and attribution. The generator and matrix validator must match the source commit.
Only current OSS/shared-SDK assignments are accepted. Any undecided capability
blocks all candidates; mixed source must be split and reviewed before selection.

The generator reads Git blobs without checking out filters or copying history.
It fails on nonportable/hidden paths, symlinks, submodules, unsupported content,
stale hashes, scan findings and unsupported licence policy. It copies no implicit
dependencies. Canonical manifests identify exact source, policy, tools, versions,
file bytes and modes. Verification rebuilds the expected artifact from source
and rejects any additional, missing or modified staging entry.

Automation always reports publication BLOCKED. The existing commercial, product,
security, qualified legal and OSS release owners retain their decisions under
ADR 0002. The [release checklist](../oss-export.md#fail-closed-release-checklist)
requires authenticated approvals bound to the manifest and independently reviewed
offline scan, dependency and reproducibility evidence. A future publisher must
validate these records before fresh-history publication; this tool has no remote
or publication operation and never accepts self-asserted approval flags.

## Consequences

- New files remain excluded by default; a source change invalidates its pinned
  digest, and any changed candidate must be rebuilt and reviewed.
- Runtime ownership, customer data access and execution/egress paths do not change.
- Basic scans are bounded tripwires, not complete disclosure or legal clearance.
  Binary/mixed-license support requires a deliberate policy extension.
- Candidate integrity is reproducible; authenticated release provenance still
  depends on the release-owner trust boundary and review records.
- No production allowlist is inferred from broad matrix areas or fabricated to
  make the release gate pass. Product extraction and publication remain future
  work with their own acceptance evidence.

## Alternatives

- Directory export from matrix areas would disclose mixed commercial modules.
- Git archive/filter/mirror publication would blur the selected-file/history
  boundary and provide no capability or licence approval.
- Executing arbitrary scanner commands or accepting approval booleans inside a
  policy would create a second trust path. Independent evidence and authenticated
  role decisions remain required at the privileged release boundary.
- A document-only plan would leave reproducibility and staging integrity untested.

## Verification

Synthetic repositories exercise independent clean-checkout reproduction, exact
allowlists, source/matrix drift, content scans, capability restrictions, symlink
rejection, destination preservation and staging integrity. Component CI and
repository documentation gates apply. See the export contract for commands and
all remaining `NOT RUN` release evidence; no legal or independent security
approval is asserted by this ADR.

## Supersession

None. This implements local candidate preparation under ADR 0002 without changing
its release ownership or granting publication permission.
