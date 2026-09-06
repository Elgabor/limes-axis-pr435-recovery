# ADR 0004: Capability settings behind one environment facade

Status: Accepted

## Context

The API configuration module owns 182 interleaved fields. Operators and
contributors need explicit ownership without renaming deployed environment
variables or changing runtime caller contracts.

## Decision

Move field declarations into seven Pydantic models: identity, persistence,
models, connectors, policy, observability and runtime. Compose them through
multiple inheritance into the existing `axis_api.config.Settings` BaseSettings
facade. Capability models do not load environment sources. Each field has one
owner; existing aliases, constraints, defaults and flat attributes are retained.

Keep capability-local validators with the owner and cross-capability production
validation at the existing startup boundary. Generate the operator reference
from class declarations without reading live configuration or publishing
credential-bearing defaults. API tests enforce reference freshness.

## Alternatives

- Nested settings would require caller migrations and a new environment naming
  contract or custom compatibility translation.
- Independent BaseSettings instances could read sources more than once and
  disagree about precedence or create stale copies after caller mutation.
- Section comments alone would leave field ownership in one large module.

## Consequences and verification

Pydantic resolves inherited fields once. Model field iteration order changes;
JSON object meaning, attributes, aliases and source precedence remain stable.
There are no nested runtime copies, adapters, new dependencies or new settings.
The baseline fixture covers all 182 fields and their environment inputs. Tests
reject duplicate capability ownership and reference drift, retain existing
runtime invariants, and verify invalid production profiles fail before app
construction. See [configuration evidence](../configuration.md).
