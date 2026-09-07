# P2: extraction gates, read failures and truthful dispatch evidence

Authorized as part of P1–P5 on 7 September 2026. Base: P1 commit
`6f7d1f96b71a72b9a43093c310ef32be05fac678`. The historical analysis remains unchanged.

## Scope and decisions

Fix the two actual bounded PostgreSQL reader defects already identified upstream
by PR #406: use the existing profile timeout and initialize a null watermark for
the no-primary-key path. Exercise both ordering branches through the real adapter
with a substituted source driver, including empty, complete and row-capped reads.

Revalidate extraction's deployment flags, binding identity, current lease state,
expiry, connector binding, broker execution evidence and permission, and current
egress policy state/connector/profile/target before source access. Reuse existing
lease and policy records; no second authorization service or secret resolver.

Preserve observed dial/read facts through errors and the dispatcher. A preliminary
gate performs no dial or extraction. A failed connection is a dial attempt without
row extraction. A later read failure retains any observed extraction. Temporary
source unavailability/timeouts are retried by the existing bounded scheduler;
configuration, schema and permission refusals remain permanent. Unknown driver
diagnostics never become public evidence. Existing tenant/claim/audit ownership
and disabled flags remain intact.

## Tests and exclusions

TDD at real adapter and dispatcher seams using synthetic SQLite, source-driver and
object-store fixtures. A10: pre-dial refusal and phase-accurate facts. A12: transient
vs permanent retry/dead-letter decisions and existing claim fencing regressions.
P3 owns durable per-batch commits/storage consistency; P4 owns live schema drift
and governed replacement bindings. No schema migration, public API shape change,
new adapter or incremental/CDC/writeback capability in P2.

Verification and independent reviews will be recorded before the P2 commit.

## Verification and review

- Red/green: the real reader first failed six cases on the nonexistent timeout;
  after that fix, three no-PK cases exposed the uninitialized watermark. All six
  empty/exact/capped PK/no-PK cases now pass through the real driver boundary.
- Red/green: expired/inactive/foreign/denied lease and mismatched binding/policy
  reached forbidden dial sentinels before the fix. Both deployment flags are also
  checked by the adapter itself.
- Red/green: connection, timeout, permission, partial read, dispatch retry and
  post-read storage failure cases now retain actual phase evidence. The existing
  attempt budget still dead-letters an exhausted transient request.
- PASS: 693 tests in the complete API connector suite (114 seconds). After review
  corrections, 92 extraction/ingestion tests pass, including all 27 P2 cases.
- PASS: worker suite 62 passed / three gated integration skips; API/worker Ruff,
  OpenAPI equality, whitespace and `make docs-check` (68 documents).
- Standards review found no hard violations and one low-priority duplication:
  repeated attempt evidence construction. A local helper now builds that evidence
  consistently; focused regressions pass.
- Spec review found SQLSTATE 28000 incorrectly retried as source unavailability.
  A new failing regression led to explicit permanent `auth_denied` classification
  for the whole SQLSTATE 28 class. The independent reviewer reran that regression
  successfully and confirmed the finding resolved.

The complete API suite and infrastructure contract checks were run during P1;
P2 changes are covered by the complete connector suite plus the focused rerun
above. Four unrelated Helm tests remain unavailable because the binary is absent.
Live source/claim/crash evidence is reserved for P3–P5; no production readiness,
new checkpoint durability or schema-drift guarantee is claimed by P2.
