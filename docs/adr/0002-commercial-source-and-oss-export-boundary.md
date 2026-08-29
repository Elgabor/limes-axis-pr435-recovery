# ADR 0002: Commercial Source And OSS Export Boundary

- **Status:** Accepted
- **Date:** 2026-08-29
- **Owners:** `@metaforismo`
- **Related:** [Issue #319](https://github.com/Limes-Labs/limes-axis/issues/319),
  [umbrella issue #284](https://github.com/Limes-Labs/limes-axis/issues/284)

## Context

`Limes-Labs/limes-axis` is a private repository and is the complete commercial
source of truth for Axis. It was public in the past, so repository visibility
cannot recall copies, Git objects or licence grants that third parties already
received. Several documents still described the superseded public-upstream,
private-downstream plan, which left release ownership and disclosure controls
ambiguous.

The repository also retains `LICENSE` and `CLA.md` from that earlier topology.
This decision changes repository and release architecture; it does not relicense
existing material, revoke an earlier grant or decide the licence for a future
OSS edition. Those legal decisions are mandatory export inputs.

## Decision

### Source-of-truth topology

| Repository | Visibility | Responsibility | History policy |
| --- | --- | --- | --- |
| `Limes-Labs/limes-axis` | Private | Complete commercial product: hosted, managed and private-deployment code, shared contracts, migrations, tests and operating documentation | Normal continuous history; commercial releases originate here |
| Future `Limes-Labs/limes-axis-oss` | Public only after approval | A deliberately useful, capability-limited edition produced from an approved export | New repository and fresh initial history; never a fork, mirror or filtered copy of the commercial repository |

The future OSS repository is a release output, not an upstream development
branch. Nothing flows automatically in either direction. An OSS contribution
may enter the commercial repository only through a normal reviewed change with
its provenance and licence verified; it does not create a second trust path
around tenancy, authorization, audit, credential, egress or execution controls.

### One-way publication flow

Every OSS publication must be reproducible from one immutable commercial commit:

1. Freeze the commercial source commit and capability-matrix revision.
2. Fail closed if any capability or path is missing from the allowlist or has an
   `undecided` disposition.
3. Materialize only allowlisted files into a clean staging directory. Do not
   clone, fork, rewrite or copy the commercial `.git` directory.
4. Verify the staged tree for secrets, customer material, proprietary paths,
   generated evidence, dependency provenance, copyright and licence policy.
5. Record a release manifest containing source commit, edition versions,
   capability-matrix revision and exported-file digests.
6. Require explicit approvals from the commercial release owner, security
   reviewer, product owner and qualified legal reviewer.
7. Create a fresh OSS commit, tag and release from the verified staging tree.

Issue [#320](https://github.com/Limes-Labs/limes-axis/issues/320) owns the
capability disposition. Issue [#321](https://github.com/Limes-Labs/limes-axis/issues/321)
owns the executable export, provenance and approval gate. Until both gates are
implemented and pass, OSS export is blocked.

### Release ownership

| Role | Decision owned | Minimum evidence |
| --- | --- | --- |
| Commercial repository maintainer (`@metaforismo` at this baseline) | Select immutable source commit and merge commercial changes | Green required checks and exact source SHA |
| Product owner | Approve capability disposition and useful-edition scope | Matrix has no `undecided` entries |
| Security reviewer | Approve disclosure boundary | Secret, history, proprietary-path and customer-material checks |
| Qualified legal reviewer | Approve licence, notices, dependency provenance and contribution treatment | Written review tied to the export manifest |
| OSS release owner | Publish only the approved tree and tag | Approval record, digests and fresh-history verification |

One person may currently hold multiple internal roles, but legal review remains
independent expertise. Automation reports evidence; it never grants approval.

### Versioning and compatibility

- Commercial and future OSS editions use independent semantic versions and
  release cadences.
- Each OSS release manifest records its commercial source SHA and version. The
  source reference is provenance, not a promise that the editions have matching
  feature sets.
- Compatibility is promised only for explicitly shared, versioned contracts
  that pass cross-edition tests: OpenAPI, published JSON Schemas and released
  SDK surfaces. Internal modules, storage layouts and deployment automation are
  not cross-edition interfaces.
- Breaking shared-contract changes require a major-version decision or an
  explicit compatibility adapter. Security fixes are triaged for both editions
  and ported through separate reviewed releases; no automatic back-merge exists.

### Disclosure threat model

| Threat | Preventive boundary | Required proof before publication |
| --- | --- | --- |
| Proprietary capability is included accidentally | Path and capability allowlist; `undecided` fails closed | Exported-tree diff matches the approved manifest |
| Secret, credential or customer evidence is included | Clean staging plus secret and forbidden-content scans; generated/runtime paths excluded | Scan reports tied to the staged-tree digest |
| Commercial Git history, tags or deleted objects leak | Fresh repository built from files only; no clone, fork or history rewrite | OSS repository has only approved fresh-history refs and no commercial Git objects |
| Licence or contributor provenance is incompatible | Dependency/source inventory and qualified legal review | Approved notices, licence decision and provenance report |
| A later edit bypasses the reviewed tree | Immutable source SHA, file digests and release-owner approval | Published commit tree matches the signed/attested manifest |
| Edition drift silently breaks shared clients | Narrow shared contracts with cross-edition compatibility tests | Contract versions and test results recorded per release |

The allowlist is the security boundary. A denylist alone is rejected because a
new commercial file would otherwise become publishable by default.

## Consequences

- Commercial development has one integration and security source of truth.
- A future OSS edition can be useful without exposing repository history or
  making every commercial module part of its public interface.
- We accept explicit export work and possible edition lag in exchange for a
  fail-closed disclosure boundary.
- We accept independent versions in exchange for avoiding false whole-product
  compatibility claims.
- Existing public copies and legal artefacts remain facts to review, not risks
  that repository privacy can erase.

## Alternatives Considered

- **Public upstream with a private downstream:** rejected because it makes the
  public repository the architectural source of truth, requires continuous
  synchronization and cannot contain the complete commercial integration. It
  also exposes every upstream history object by design.
- **One repository with licence or feature flags:** rejected because runtime
  flags do not prevent source or history disclosure and would make release
  callers understand internal commercial boundaries.
- **Filtered-history or subtree publication:** rejected because rewriting still
  processes commercial history and makes absence of unreachable objects harder
  to prove than a files-only fresh export.
- **No OSS edition:** rejected because a useful future OSS edition remains a
  product goal; the decision is to make its publication deliberate and safe.

## Verification

- Focused repository-topology documentation tests.
- `make docs-check` for repository-local links.
- GitHub repository metadata confirmed `Limes-Labs/limes-axis` is private on
  2026-08-29.
- `NOT RUN`: an OSS export, fresh-history inspection and cross-edition contract
  tests; these belong to #320/#321 and no OSS repository exists yet.
- `NOT RUN`: qualified legal review of `LICENSE`, `CLA.md`, historical grants,
  dependency provenance or the future OSS licence.
- `NOT RUN`: independent security review of the export threat model.

## Supersession

None.
