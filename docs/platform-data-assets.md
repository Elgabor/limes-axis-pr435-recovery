# Platform Data Asset Catalog

The data asset catalog introduces the governed layer between connectors and
the ontology: a tenant-scoped, metadata-only read model that projects
connector manifests and sync evidence into stable, addressable data assets.

## Contract

`GET /data/assets?tenant_id=…` returns the catalog for one tenant. The
endpoint lives on the dedicated `/data` plane — it is a first-class platform
surface, not part of the demo operations namespace, and it never receives the
legacy `/demo/manufacturing` alias.

Each connector projects into exactly one asset with the stable identity
`source:<connector_id>:default`. The `kind`, evidence and governance
vocabularies are already granular (`table`, `view`, `topic`, `object_prefix`,
…) so later resource-level discovery slices can narrow assets without breaking
consumers; today every asset is the connector-level `default` aggregate.

## Evidence states

Evidence describes what Axis has actually observed, never what it hopes:

- `sync_observed` — a completed connector run exists for this source.
- `preview_only` — metadata was inspected through a preview, no sync yet.
- `declared_only` — only the manifest declares this source.

A failed run never downgrades an existing observation: evidence derives from
the latest successful run, mirroring the connector registry read model.

## Governance states

Governance is declared honestly and nothing is invented:

- `declared` — an operator declared owner, classification, residency and
  retention through the persistent stewardship registry.
- `partial` — the manifest declares semantic field mappings, no stewardship
  declaration exists yet.
- `not_declared` — no schema mapping and no stewardship declaration.

## Stewardship registry

Stewardship lives in its own append-only revision history
(`data_asset_stewardship_records`, migration 0058), never inside the
connector manifest. Declarations are addressed by catalog asset ID:

- `GET /data/assets/{asset_id}/stewardship` returns the current declaration
  or null.
- `PUT /data/assets/{asset_id}/stewardship` declares a new revision with
  optimistic concurrency (`expected_revision`) and idempotency keys.
  Structured `409`s distinguish a stale revision from a replayed key with a
  changed payload.
- Writes resolve the asset against the live catalog first: stewardship for an
  unknown asset fails closed instead of orphaning evidence.
- Advisory transaction locks serialize declarations across replicas,
  including the first declaration where no row exists to lock.
- Verified OIDC principals own their declarations; the request body cannot
  spoof `declared_by`.
- Every accepted declaration appends `data.stewardship.declared` or
  `data.stewardship.updated` audit evidence.

The console renders the current declaration in the asset detail pane and
offers an inline declare form when none exists.

## Metadata-only boundary

The catalog is metadata-only by contract. Preview sample rows stay inside the
connector boundary: the projection copies schema fields, targets and runtime
policy metadata, and cannot carry `sample_rows`, credential material or source
values. A regression test injects a secret marker row into a preview sample
and asserts neither the value nor the field name reaches the response.

## Authorization

The endpoint binds reads to the verified OIDC principal when present: an
authenticated principal whose tenant differs from the query tenant receives
the canonical structured `403`. Unknown tenants return the shared structured
`404`. Unauthenticated demo traffic keeps working under the existing
demo-mode convention.

## Console surface

The Data page (`/data`) renders metrics, a searchable URL-backed list and the
asset detail pane: identity, evidence/governance, runtime boundary, egress
and payload policies, declared schema mapping and ontology targets. Deep links
use opaque asset IDs and fail closed: an unknown asset ID shows an explicit
not-found state instead of silently substituting another asset.
