# ADR 0016: Versioned performance workloads and comparable evidence

- **Status:** Accepted
- **Date:** 2026-09-07
- **Owners:** @metaforismo
- **Related:** [Issue #361](https://github.com/Limes-Labs/limes-axis/issues/361), [performance contract](../performance-baseline.md)

## Context

Axis has local lineage and connector-waterfall measurements, plus a Kubernetes
load rehearsal, but no common workload, artifact format or noise policy for
performance changes. Fast error responses, different fixture sizes and machine
noise can otherwise look like improvements. Production services and several
future capabilities are not available in a generic developer checkout.

## Decision

Deployment owns the measurement contract. Data, workflow, intelligence and
experience owners maintain their journeys and functional completion assertions.
Keep versioned SME/enterprise shapes and budgets in one checked workload manifest.
Use disposable synthetic fixtures through the current HTTP/domain/SQL paths,
with explicit identity and external-port fakes. Never accept a user-supplied
network target or operator database in this local runner.

Retain scheduled arrivals, failures/drops, validated work, SQL timing/counts,
pool connection-time, resources and source/runtime provenance. Provide fixed-rate
load and soak modes plus separate Python wall-stack profiles. Gate comparisons
on compatible evidence and a documented three-trial noise allowance. Keep
deterministic harness tests in CI; require measured review evidence for changes
that affect performance instead of gating shared-runner milliseconds.

## Consequences

- Developers can reproduce overhead and cardinality observations without
  configuring external services or modifying application behavior.
- Runtime/security invariants remain in their existing owners; benchmark
  instrumentation and adapters are only imported by the local script/tests.
- The local enterprise shape does not prove a distributed enterprise deployment.
  SQLite, fake IdP/provider/runtime ports, missing search and other unmeasured
  surfaces must remain explicit in every report.
- A dataset, environment or harness change invalidates direct comparison.
  Source changes are allowed and identified by revision and runtime digest.
- Profiles provide limited Python stack attribution. Native CPU, asynchronous
  causal stacks, provider internals and production capacity require other evidence.

## Alternatives

Use only existing microbenchmarks: cheap, but lacks common arrivals, resources,
functional assertions and comparison policy. Run only a cluster load tool:
necessary for deployment evidence, but not reproducible offline and currently
targets reachability rather than all critical product journeys. Add a mandatory
load-testing/profiling service: unnecessary dependency for this foundation.

## Verification

Focused tests exercise actual HTTP journeys across both fixture shapes, identity
and tenant denial, blocked socket access, environment isolation, SQL failures,
timeouts, bounded saturation, artifact integrity, profiling output and comparison
noise/regression cases. The baseline report carries measured evidence; local
component CI does not imply deployed SLO acceptance.
