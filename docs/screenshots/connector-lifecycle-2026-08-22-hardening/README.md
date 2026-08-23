# Connector activation lifecycle - fresh UI evidence

Captured 2026-08-22 against the real local demo stack (FastAPI on
`127.0.0.1:8000`, Next.js console on `127.0.0.1:3100`, Postgres-backed
persistence) by driving the actual product through Playwright Chromium:
connector registered via the Add-connector wizard with a real CSV preview,
then activated through the lifecycle panel.

These images replace the stale set under `connector-activation-2026-08-22/`,
which predates the lifecycle copy, denial-reason copy, revision-trail, and
mobile overflow fixes from this work cycle. The older folder is kept
untouched for history.

## What each file shows

| File | Proves | Does not prove |
| --- | --- | --- |
| `01-desktop-detail-registered.png` | A freshly wizard-registered connector renders `Registered Preview Only` with operator copy explaining what stays blocked, an `r1 Registration recorded` trail entry, and a single clear `Activate for previews` action. | Nothing about SSO-gated deployments (this demo tenant runs without OIDC enforcement); nothing about server-side transition rules. |
| `02-desktop-runs-gate.png` | Before activation the Runs tab names the blocker and points to the Overview tab instead of offering a dead sync form. | That sync succeeds after activation (credential lease is intentionally absent here). |
| `03-desktop-active-with-history.png` | After keyboard-free one-click activation the pill flips to `Active Preview`, state copy changes, and the same revision's trail entry records the transition audit event. | Live operation; egress boundary remains `no-external-egress`. |
| `04-desktop-live-enablement-gated.png` | Live enablement honestly lists all three unmet API preconditions (`Missing` pills), asks for approval/policy/credential evidence, and keeps the submit disabled - no synthetic readiness. | The API's 422 rejection path (the console gates first); a connector whose runtime policy actually permits live operations. |
| `05-mobile-active-overview.png` | At 412 px the detail card, tabs strip, lifecycle panel, and trail stay inside the viewport with no horizontal page overflow (verified `body.scrollWidth == 412`). | Tablet/iPhone-specific rendering; only Pixel-class width was captured. |
| `06-mobile-live-enablement-gated.png` | The live-enablement requirements list, evidence field, and disabled submit render legibly at phone width. | Touch-interaction ergonomics beyond layout. |

## Honest limitations

- All writes ran in demo mode (unauthenticated demo principal). Scope-denial
  copy (`missing_manifest_lifecycle_scope` / `missing_manifest_live_scope`)
  is covered by component tests, not screenshots, because triggering it
  requires an SSO session lacking those grants.
- Registry entries named `E2E lifecycle *` visible in some shots are records
  created by the automated browser tests earlier the same day against this
  shared local database; they are real product data, not mockups.
- No secrets, tokens, or personal data appear; all identifiers are synthetic
  demo-tenant values.
