# Approval review workspace

Issue [#436](https://github.com/Limes-Labs/limes-axis/issues/436) refines `/approvals` after the console clarity work in [#433](https://github.com/Limes-Labs/limes-axis/issues/433).

| Before | After | Why |
| --- | --- | --- |
| Three full metric cards precede the queue on mobile. | Pending, high-risk and decided counts share one compact row. | Show more actionable work in the first viewport while retaining provenance. |
| Every pending action appears in one unfiltered list. | Search, risk and domain filters show the matched count against the returned pending queue. | Find an action, owner or workflow without confusing the filtered count with total work. |
| Selecting a mobile row updates a detail pane farther down the document. | The detail replaces the queue below 1024px; returning restores focus to the opener. | Make selection and return explicit for touch and keyboard users. |
| Owner context is at the bottom of the detail. | Risk, due time and owner appear together below the action summary. | Put decision context before the choice. |
| The decision rail truncates permission and owner values and animates continuously. | A collapsed, static trail wraps full values; attached controls are labelled required. | Keep context inspectable without implying that attached controls have been evaluated. |

## Navigation and data boundaries

- Search preserves spaces during entry; matching trims the query and ignores case. It matches the action, summary, owner, requester, workflow, approval ID, domain and tenant domain label.
- Filters apply only to the actionable records returned by the existing tenant-bound API. Terminal decisions remain in the server-derived decision history.
- Filter edits replace the URL history entry and clear the selected record. Clicking a row pushes its approval ID; arrow-key traversal replaces the selection.
- An explicit approval or action-run link takes precedence over filters. A pending linked approval excluded by the filters remains reviewable with an explanation and a reset action. A missing record never falls back to another approval.
- Mobile review focuses the detail region. Return focuses the original row, or the queue heading if that row is no longer available.
- Decision options, identity and permission checks, confirmation, API payloads, audit persistence, action-run links and external-executor semantics use the existing implementations.
- The browser retains search keystrokes while Next updates the URL. External reset and Back/Forward restore the URL value without rewriting the field during typing.

## Verification

`make verify` covers the repository's local component and contract gates. Live browser tests remain a separate lane and require an isolated migrated demo database and API, as described in [development](development.md).

The approval review group in `e2e/control-room.spec.ts` runs in `test:e2e:live:read`, before stateful tests consume the three seeded approvals. It checks rapid multiword typing, composed filters, reset, browser history, mobile focus, missing and filtered-out deep links, dialog cancellation, and horizontal overflow on all three configured browser projects. The density test explicitly substitutes browser responses for 30 long records, one record and an empty queue; these are layout fixtures, not production capacity evidence.

`e2e/approvals-console.spec.ts` exercises keyboard selection, the real decision endpoint, persisted outcomes and the exact audit-event link. Its mutation lane runs once on desktop against the isolated database. Its queue read respects `AXIS_E2E_API_BASE_URL` so it uses the same API as the application build.

Visual review covers light and dark themes at 390px, 768px and 1280px. Screenshots and command outcomes are attached to the delivery review separately from the source change; local evidence does not imply deployment or hosted CI success.
