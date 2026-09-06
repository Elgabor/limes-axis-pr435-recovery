# OSS export candidate and release gate

Issue [#321](https://github.com/Limes-Labs/limes-axis/issues/321) implements local
candidate preparation under [ADR 0002](adr/0002-commercial-source-and-oss-export-boundary.md)
and [ADR 0013](adr/0013-oss-candidate-provenance-gate.md). The commercial repository
remains private. A candidate is an **internal review artifact**, not a release or
permission to publish. No OSS repository, tag, remote, upload or automatic sync
is created by this tool.

## Inputs and ownership

The release owner selects a clean checkout at a full immutable commit ID, explicit
commercial/OSS versions and a reviewed, committed JSON file allowlist. The
[edition matrix](editions.md) remains the disposition owner. Its areas are an
inventory, not export units: assigning an entire mixed directory to `oss` is
invalid. Product and code owners must inspect each selected file and its imports,
resources, migrations and generated contracts before recording all capabilities
it contains. If a file contains Hosted or Enterprise code, split that boundary
through a commercial PR first; deleting names or adding feature flags does not
make it exportable.

The generator can validate declared mappings and their containing matrix areas;
it cannot infer the semantics of arbitrary source code. A deliberately or
accidentally incomplete capability assignment remains a human review blocker.
No production allowlist is supplied by #321. Synthetic test mappings demonstrate
the mechanism without authorizing any current product file.

The standard-library [generator](../scripts/prepare_oss_export.py) reads committed
Git blobs only. The generator and matrix checker must themselves match that
commit. It does not execute exported code, dependency installers, source hooks,
Git filters, external scanners or networking. Existing API identity, tenant,
permission, audit, transaction and egress owners are unaffected.

## Exact allowlist format

This abbreviated example is **not executable release input**. Replace every
placeholder with reviewed facts, include the complete selected file list, and
commit it. Paths remain unchanged between source and candidate; no globs,
directory expansion, renaming, rewriting or implicit dependency inclusion exists.

```json
{
  "schema_version": 1,
  "commercial_version": "1.0.0",
  "oss_version": "0.1.0",
  "matrix_sha256": "<sha256 of docs/edition-capabilities.toml bytes>",
  "license": "<reviewed license identifier>",
  "files": [
    {
      "path": "LICENSE",
      "sha256": "<sha256 of committed LICENSE bytes>",
      "capabilities": [],
      "spdx": "<same reviewed identifier>",
      "attribution": "<exact copyright attribution retained in NOTICE>"
    },
    {
      "path": "NOTICE",
      "sha256": "<sha256 of committed NOTICE bytes>",
      "capabilities": [],
      "spdx": "<same reviewed identifier>",
      "attribution": "<exact copyright attribution retained in NOTICE>"
    },
    {
      "path": "packages/sdk-python/src/axis_sdk/client.py",
      "sha256": "<sha256 of reviewed file bytes>",
      "capabilities": ["SDK-PYTHON"],
      "spdx": "<same reviewed identifier>",
      "attribution": "<exact copyright attribution retained in NOTICE>"
    }
  ]
}
```

Only `LICENSE` and `NOTICE` are legal-file exceptions to capability mapping.
Every other file needs current `oss` or `shared-sdk` capabilities whose matrix
areas contain that path. An `undecided` entry anywhere blocks preparation;
planned capabilities cannot authorize existing source. Unknown/extra fields,
duplicate JSON keys or paths, case collisions, changed matrix/file digests and
unsupported licences fail closed. Version labels are release-owner declarations;
the maintainer must reconcile them with package metadata during release review.

The initial policy supports one declared SPDX identifier per candidate:
`Apache-2.0`, `MIT` or `BSD-3-Clause`. It checks license-family text, matching SPDX
headers where present, nonempty attributions and their presence in `NOTICE`.
Those checks do not establish licence compatibility, completeness, copyright
ownership or permission to relicense. Mixed licensing, additional licence texts,
SPDX expressions and binary assets require a reviewed policy extension before
preparation. Historical `LICENSE`/`CLA.md` files are not a release approval.

## Prepare, inspect and reproduce

Use Python 3.12 or 3.13 and Git in a private workspace with exclusive write
access for the preparation/review process. Partial/promisor clones and configured
Git filters are rejected before inspecting checkout status. Dependencies, `.venv` and
other ignored build files may exist but are never read as export inputs. Tracked
changes, staged changes and nonignored untracked files block preparation. Use a
fresh destination outside the source checkout and all Git storage, with an
existing private parent directory. The candidate root is created with mode 0700.

```sh
python3 scripts/prepare_oss_export.py build \
  --repo-root /private/review/source \
  --commit FULL_IMMUTABLE_COMMIT_ID \
  --policy release/oss-allowlist.json \
  --candidate /private/review/candidate-a

python3 scripts/prepare_oss_export.py check \
  --repo-root /private/review/source \
  --commit FULL_IMMUTABLE_COMMIT_ID \
  --policy release/oss-allowlist.json \
  --candidate /private/review/candidate-a
```

Use actual private paths; these paths are placeholders. The output has:

- `tree/`: exact selected bytes and committed executable bits, without `.git`;
- `manifest.json`: source commit, versions, policy/matrix/generator digests,
  each file's path, size, mode, SHA-256, capability assignment and attribution,
  automatic check names and all pending release decisions;
- `manifest.sha256`: SHA-256 of the canonical JSON bytes.

The generator adds no timestamps, host paths or remote URLs. The manifest retains
reviewed policy declarations and attributions; content tripwires cannot certify
that arbitrary input is secret-free. Its source SHA and inventory can also
disclose commercial metadata, so the manifest stays private until its disclosure
is explicitly reviewed. A checksum
provides integrity comparison, not an authenticated signature or human approval.

Repeat `build` using an independently obtained clean checkout of the same commit
and the committed generator, targeting `candidate-b`. Run `check` on both and
compare their manifest digests and entire directories. `check` regenerates the
expected artifact from pinned source; it does not trust claims inside an edited
manifest. It rejects additional files, empty directories (including `.git`),
missing files, symlinks, changed bytes and changed file permissions. Interrupted
writes leave an incomplete private directory; inspect it and select a new
candidate path. The tool never overwrites or deletes an existing candidate.

## Automated content checks and limits

Preparation rejects hidden/runtime/generated paths, credentials/database/archive
suffixes, symlinks, submodules, LFS pointers, non-UTF-8/binary/control content and
oversize input (1,000 files, 2 MiB per file, 20 MiB total). It scans selected text
for private-key headers, common token shapes, long credential assignments and
proprietary/confidential markers. Errors report the rule, never the matched
secret or file content. No scan-ignore mechanism is provided.

These deterministic rules are conservative tripwires. They can reject benign
fixtures and miss unsupported token formats, encoded content, customer facts or
proprietary logic without markers. A PASS is **not** a complete secret, customer,
proprietary-code, dependency or legal audit. Before release, security must run
an independently reviewed scanner offline, with credential verification and
telemetry disabled, and bind its tool/rule versions, full selected-file coverage,
configuration and zero-unresolved-finding result to this manifest digest. Scan
errors or skipped files block release. Findings stay in access-controlled
internal evidence; do not put raw matches in a PR or public manifest.

## Fail-closed release checklist

Every generated manifest says `release_status: BLOCKED`. `build`/`check` exit 0
means candidate preparation/integrity PASS only. No approval JSON flag, CLI
switch, script result or merge of this issue can change publication permission.
A future privileged release workflow must consume authenticated approval records;
#321 supplies the local generator and review contract, not that publisher.

Before an OSS release owner creates a fresh repository or publishes anything,
all of the following must be recorded in an access-controlled release review:

1. Freeze source commit, complete allowlist, versions and generator revision.
   Run matrix validation and both independent preparations; retain matching
   manifest digests and full-tree verification results.
2. Product owner approves a useful edition and complete per-file capability
   mapping. Build/test the candidate itself in isolation; record dependencies,
   lock files, package versions, notices/SBOM, provenance and shared-contract
   tests. Private imports, missing runtime assets or unknown provenance block.
3. Security reviewer approves offline scan evidence, absence of customer material,
   generated operational evidence, secrets and closed modules, plus file-only
   staging inspection. No remote credential validation is authorized by scanning.
4. Qualified legal reviewer gives written approval of the exact source/dependency
   inventory, licence text, notices, historical grants and contribution treatment.
   Independent legal expertise remains required even if internal roles overlap.
5. Commercial release owner explicitly approves the source revision and artifact.
   Each role's authenticated record states identity, role, decision, manifest
   SHA-256, source commit, policy digest, evidence references and any expiry or
   conditions. Missing, rejected, expired or unverifiable records block release.
   A local string claiming somebody approved is not an approval record.
6. OSS release owner rechecks all records and the untouched artifact immediately
   before publication. Any source, mapping, tool, scan-policy, dependency or tree
   change invalidates the affected evidence and approvals; rebuild and review.
7. In a separately authorized publication task, initialize fresh Git history from
   **only** `tree/`. Never fork, mirror, filter or copy commercial Git objects,
   refs, hooks or configuration. Review initial refs/objects, compare published
   file bytes and modes to the approved manifest, and bind the fresh commit/tag
   to the approval record. Later releases also carry only approved file changes.

Future workflow credentials belong to the release owner and cannot be granted
by the candidate generator. Rollback or removal of a public release cannot recall
already distributed copies; a disclosure incident requires the security process.

## Verification boundary

[Executable tests](../services/api/tests/test_oss_export.py) use synthetic Git
repositories, independent clean clones and deliberately nonfunctional sensitive
fixtures to verify reproducibility, exclusion, integrity and rejection behavior.
Run `make test-api PYTEST_ARGS='tests/test_oss_export.py -q'` and `make verify`.

`NOT RUN`: a curated Axis OSS candidate, a useful-edition build, dependency/SBOM
review, independent offline scan, qualified legal/security approvals, fresh
public-history inspection and actual publication. These are release gates, not
claims satisfied by synthetic tests or commercial CI. Closing #321 delivers the
export design and local preparation/provenance implementation.
