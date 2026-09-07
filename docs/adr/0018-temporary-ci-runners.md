# ADR 0018: Temporary CI runners for a reviewed pull request

- Status: Accepted
- Date: 2026-09-07

## Context

GitHub-hosted CI can stop before executing repository code when its allowance
is exhausted. Local component tests do not replace the Web, Python and live-API
checks, and increasing paid usage is not required to maintain these gates.

## Decision

Allow an administrator to route the existing three CI jobs for one reviewed,
same-repository PR head to temporary self-hosted Linux runners. Two repository
variables identify that exact head and a unique runner label set. Other heads,
forks and push events retain the hosted default. Job names, permissions and
verification steps remain the same; self-hosted dependency caching is disabled
to avoid remote cache uploads.

Run each job with a just-in-time runner registration in a disposable VM. Share
no host directories, Docker socket, SSH agent or long-lived credentials. A
reviewed run may execute its three jobs sequentially in separate work directories
inside one VM. The VM owns its Docker daemon and synthetic service fixtures.
Clear routing variables, remove unused registrations and stop the VM afterward.

The SHA gate is a routing safeguard, not protection against repository writers
who can change workflows. Isolation and ephemeral credentials are the trust
boundary. No successful check is synthesized from local test output.

## Alternatives

- Wait for the hosted allowance to reset: valid, but blocks delivery meanwhile.
- Increase paid usage: unnecessary when the operator supplies a runner.
- Run tests locally and bypass CI: loses actual workflow and integration evidence.
- Keep a permanent runner on a developer host: expands credential and filesystem
  exposure and requires ongoing operations beyond this task.

## Consequences and verification

Operators supply machine resources and explicitly review each new head. ARM64
Linux can validate the same workflow but does not prove x86 image compatibility.
No production deployment, repository export or billing change is involved.

Validate workflow syntax and documentation, execute all three existing jobs on
the final PR head, and verify their actual runners and conclusions before merge.
The [development guide](../development.md#temporary-self-hosted-ci) describes
setup, evidence and cleanup. Historical local tests remain separately reported.
