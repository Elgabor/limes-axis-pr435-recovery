# P5: controlled connector proof and next adapter decision

Base: P4 `2336d36`. This phase exercises implemented paths and records their
limits; it does not label the whole connector SDK production certified.

## Reproducible proof

Run from `services/api` in an environment restored from its existing lockfile:

```sh
python scripts/verify_connector_standardization.py
python scripts/verify_connector_standardization.py --postgres-port 62903
```

The first command is offline. The second explicitly creates synthetic databases,
roles and schemas on the supplied loopback PostgreSQL port. Supply only a dedicated
test instance. The runner clears deployment `AXIS_*` variables and disables `.env`
loading. It does not provision Docker, contact a graph service, install packages or
change a shared deployment. The integration data remains in that test instance.

For this run: official PostgreSQL 16 image digest
`sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94`,
container `limes-connectors-p1-p5-01a07d85`, published only on loopback with tmpfs
storage. Source roles have schema usage and SELECT, with no INSERT privilege.
Separate databases and connection pools serve Axis metadata and source fixtures.
No credentials or connection strings are recorded here.

## Dataset and contract

PostgreSQL contains purchases L1–L5 (`order_id`, numeric amount and synthetic note).
The seed's compact JSON array SHA-256 is
`07126a8b534d3171620bab85701ed233afa9476f8625cb566c04642012cee774`.
CSV contains confirmations C1–C5 referring to L1–L5; initial file SHA-256 is
`f6a0133485178d79bee911b28af538421d93403343bedb70eb3cf2f37bba90e9`.
The legacy CSV fixture translates its ID/name/risk columns to the existing proposal
shape; this is synthetic mapping, not an approved industrial ontology.

- Legacy CSV/PostgreSQL host contract: `0.1`, `legacy_proposals`, snapshot bounded;
  no incremental, CDC, writeback or verified durable legacy offset resume.
- Qualified raw consumer: bounded PostgreSQL selection, `raw_batch_v1` checkpoint
  identity/provenance, `postgres_schema_v2`, envelope schema as declared by runtime.
- Source pages: two rows; separate runs with total caps three and ten.
- Enabled test flags: source-ingestion dispatch/extraction and runtime egress
  enforcement against the approved synthetic endpoint. Production defaults remain off.
- Source selection consistency: read-only REPEATABLE READ, ACCESS SHARE table lock;
  no cross-selection snapshot promise. Different governed requests are new snapshots.

## Evidence matrix

| Scenario | Observed result |
| --- | --- |
| Five rows, cap ten | PostgreSQL reads pages 2/2/1 on a stable snapshot and stores five raw rows. CSV returns 2/2/1 proposal batches with completion evidence remaining unknown. |
| Total cap three | PostgreSQL stores three raw rows with `row_limit` and truncation. CSV returns 2/1 proposal batches with `row_limit`. Neither result claims the complete dataset. |
| Source update/new generation | L2 changes and L6 is added; a new request reads six rows (or the declared cap) and preserves the old content-addressed object. CSV C2 changes/C6 is added in a separate file generation; original fixture bytes remain unchanged. |
| Concurrent source update | After page one, another source connection changes L3 and inserts L6. The current selection still returns the original five-row snapshot; the source independently contains six rows. |
| Replay/storage integrity | Identical completed request is not claimed again. Post-commit restart verifies and reuses its stored object. Corrupt bytes fail closed. Streamed remote-store verification is bounded and closes/releases responses on success and failure. |
| Process interruption | A separate Python process exits immediately before or after metadata commit. Before commit an orphan remains detectable and retry rereads; after commit the durable batch is reused. A physically separate PostgreSQL connection sees batch one before source read two. |
| Access and claims | Expired Axis lease prevents source I/O; revoked source SELECT gives dial=true/read=false. Token loss and expiry prevent batch/audit/final advancement. Validate-only records zero acquisition. |
| Transient source failure | A held table lock causes a real statement timeout. No output advances; after release the bounded retry completes. |
| Schema drift | Type modifier, renamed column and removed PK each cause dial=true/read=false. Discovery and explicit predecessor replacement permit a new governed request. No-PK output carries no watermark or strong resume claim. |
| Payload confinement | Synthetic row canaries exist in object payloads, not request evidence or audit. No graph consumer is invoked and the runtime issues no source mutation. |

The SELECT-only role exposed a defect missed by privileged/fake sources:
`information_schema.table_constraints` hid its primary key. P5 reuses the catalog
key evidence already checked under the schema snapshot, without broader grants.
The regression exercises the real least-privilege source role.

## One next adapter selected

Select an **immutable S3/MinIO object-drop adapter feeding raw envelopes**, aligned
with #335 under #277. An object version ID plus checksum provides a concrete source
identity for safe replay, and it reuses the raw transaction/storage boundary proved
here. Do not add a polling incremental profile without a reliable modification key
and deletion contract. This is P5's adapter choice, not an unimplemented capability
being advertised as supported or an authorization to deploy a new provider.

Live issue check on 2026-09-07: #342 is CLOSED; #277 remains OPEN with source-family
slices. Earlier remote PRs #407/#410 deliver a separate offline SDK contract and
conformance work. This checkout's host 0.1 and runtime proof remain distinct from
that SDK; no issues, pull requests or shared runtime were modified.

## Explicit limits

No actual S3 service/WORM outage rehearsal, hardware power-cut, industrial mapping
approval, graph promotion, production secret broker, production load certification,
CDC, incremental or deletion capture was performed. The CSV fixtures are immutable
by test setup; the legacy reader still declares its mutable-source/offset limits.
No new adapter implementation is bundled with this proof. Browser interaction is
covered by React component tests; no live browser deployment is claimed.

## Final verification and review

- Full API suite: **1,932 passed, 57 skipped, 4 deselected**. The four deselected
  deployment rendering/schema/lint checks require Helm, which is not installed;
  they are **NOT RUN**. Skips cover optional integration environments, including
  PostgreSQL cases executed separately by the isolated proof runner.
- Full web suite: **981 passed across 106 files**. Full worker suite:
  **62 passed, 3 skipped** for optional integration environments.
- Reproducible offline connector proof: **93 passed**; isolated PostgreSQL proof:
  **20 passed**, including migration, process interruption, lease fencing,
  least-privilege discovery/extraction and batch-conflict finalization outside
  the locked transaction. These focused counts overlap the broader suites.
- Python lint, web TypeScript checking and focused ESLint passed. Documentation
  validation passed for 71 files and 41 capabilities. Security posture, deployment
  package, container image/release/security-scan and vulnerability-management
  contract checks passed; these checks do not represent an actual image build,
  vulnerability scan or deployment.
- Independent standards review: the cap-three/cap-ten evidence wording was
  corrected into separate matrix rows; no remaining blocking findings were
  reported. The least-privilege catalog fix and bounded fallback were reviewed.
- Independent specification review: no blocking findings against the P5 scope
  and A8–A13 evidence; the reviewer also independently reproduced all 93 offline
  proof tests. The next adapter is a documented choice, not a delivered adapter.
