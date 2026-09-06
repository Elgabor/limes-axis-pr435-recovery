from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import NamedTuple


class CheckResult(NamedTuple):
    name: str
    ok: bool
    detail: str


def required_workflow_files() -> tuple[str, ...]:
    return (".github/workflows/container-release.yml",)


def required_workflow_permissions() -> tuple[str, ...]:
    return (
        "contents: read",
        "packages: write",
        "id-token: write",
        "attestations: write",
    )


def required_workflow_terms() -> tuple[str, ...]:
    return (
        "workflow_dispatch",
        "push:",
        '"v*"',
        "build-images:",
        "validate-promotion-evidence:",
        "publish-images:",
        "needs: build-images",
        "environment:",
        "name: axis-container-release",
        "release_approval_issue",
        "rollback_plan_issue",
        "rollback_drill_id",
        "rollback_plan_acknowledged",
        "Validate promotion evidence",
        "gh issue view \"$RELEASE_APPROVAL_ISSUE\"",
        "gh issue view \"$ROLLBACK_PLAN_ISSUE\"",
        "ghcr.io/${{ github.repository_owner }}/limes-axis-api",
        "ghcr.io/${{ github.repository_owner }}/limes-axis-web",
        "ghcr.io/${{ github.repository_owner }}/limes-axis-worker",
        "services/worker/Dockerfile",
        "docker/setup-buildx-action@v4.3.0",
        "docker/login-action@v4.6.0",
        "docker/metadata-action@v6.2.0",
        "docker/build-push-action@v7.3.0",
        "actions/attest-build-provenance@v4.2.2",
        "sigstore/cosign-installer@v4.1.2",
        "provenance: mode=max",
        "sbom: true",
        "push: ${{ github.event_name == 'workflow_dispatch' && inputs.push == true }}",
        "cosign sign --yes",
        "push-to-registry: true",
    )


def required_docs_terms() -> tuple[str, ...]:
    return (
        "make container-release-check",
        "container-release-check",
        "keyless signing",
        "SBOM",
        "provenance",
        "release approval issue",
        "rollback plan issue",
        "rollback drill",
        "GitHub Environment reviewer protection",
        "axis-container-release",
        "not a production certification",
    )


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _make_targets(makefile_text: str) -> set[str]:
    return {
        match.group(1)
        for match in re.finditer(r"^([A-Za-z0-9_.-]+):(?:\s|$)", makefile_text, re.MULTILINE)
    }


def _missing_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    normalized = text.casefold()
    return [term for term in terms if term.casefold() not in normalized]


def check_workflow_file(repo_root: Path) -> list[CheckResult]:
    missing = [
        relative for relative in required_workflow_files() if not (repo_root / relative).exists()
    ]
    return [
        CheckResult(
            "container_release.workflow_file",
            not missing,
            "container release workflow is present"
            if not missing
            else f"missing: {', '.join(missing)}",
        )
    ]


def check_workflow_terms(repo_root: Path) -> list[CheckResult]:
    workflow = repo_root / ".github" / "workflows" / "container-release.yml"
    if not workflow.exists():
        return [
            CheckResult(
                "container_release.workflow_terms",
                False,
                "container-release.yml is missing.",
            )
        ]

    text = _read_text(workflow)
    missing = _missing_terms(text, required_workflow_terms())
    return [
        CheckResult(
            "container_release.workflow_terms",
            not missing,
            "workflow builds API and web images with SBOM, provenance and signing"
            if not missing
            else f"missing terms: {', '.join(missing)}",
        )
    ]


def check_workflow_permissions(repo_root: Path) -> list[CheckResult]:
    workflow = repo_root / ".github" / "workflows" / "container-release.yml"
    if not workflow.exists():
        return [
            CheckResult(
                "container_release.workflow_permissions",
                False,
                "container-release.yml is missing.",
            )
        ]

    text = _read_text(workflow)
    missing = _missing_terms(text, required_workflow_permissions())
    return [
        CheckResult(
            "container_release.workflow_permissions",
            not missing,
            "workflow has registry, attestation and OIDC permissions only where needed"
            if not missing
            else f"missing permissions: {', '.join(missing)}",
        )
    ]


def check_make_target(repo_root: Path) -> list[CheckResult]:
    makefile = repo_root / "Makefile"
    if not makefile.exists():
        return [CheckResult("container_release.make_target", False, "Makefile is missing.")]

    targets = _make_targets(_read_text(makefile))
    return [
        CheckResult(
            "container_release.make_target",
            "container-release-check" in targets,
            "container-release-check Make target is present"
            if "container-release-check" in targets
            else "Makefile is missing container-release-check target",
        )
    ]


def check_ci_gate(repo_root: Path) -> list[CheckResult]:
    ci = repo_root / ".github" / "workflows" / "ci.yml"
    if not ci.exists():
        return [CheckResult("container_release.ci_gate", False, "CI workflow is missing.")]

    text = _read_text(ci)
    return [
        CheckResult(
            "container_release.ci_gate",
            "make container-release-check" in text,
            "CI runs the container release contract check"
            if "make container-release-check" in text
            else "CI does not run make container-release-check",
        )
    ]


def check_docs(repo_root: Path) -> list[CheckResult]:
    expectations = (
        (
            "container_release.deployment_docs",
            repo_root / "docs" / "deployment.md",
            required_docs_terms(),
        ),
        (
            "container_release.readme_link",
            repo_root / "README.md",
            ("container-release-check", "keyless signing", "SBOM"),
        ),
        (
            "container_release.plan_tracking",
            repo_root / "plan.md",
            ("Add container release provenance, signing and SBOM workflow baseline",),
        ),
    )
    checks: list[CheckResult] = []
    for name, path, terms in expectations:
        if not path.exists():
            checks.append(CheckResult(name, False, f"{path.name} is missing."))
            continue
        text = _read_text(path)
        missing = _missing_terms(text, terms)
        checks.append(
            CheckResult(
                name,
                not missing,
                f"{path.name} documents the container release boundary"
                if not missing
                else f"missing terms: {', '.join(missing)}",
            )
        )
    return checks


def run_static_checks(repo_root: Path) -> list[CheckResult]:
    repo_root = repo_root.resolve()
    checks: list[CheckResult] = []
    checks.extend(check_workflow_file(repo_root))
    checks.extend(check_workflow_terms(repo_root))
    checks.extend(check_workflow_permissions(repo_root))
    checks.extend(check_make_target(repo_root))
    checks.extend(check_ci_gate(repo_root))
    checks.extend(check_docs(repo_root))
    return checks


def _print_results(results: list[CheckResult], *, json_output: bool) -> None:
    if json_output:
        print(
            json.dumps(
                [
                    {"name": result.name, "ok": result.ok, "detail": result.detail}
                    for result in results
                ],
                indent=2,
                sort_keys=True,
            )
        )
        return

    for result in results:
        status = "OK" if result.ok else "FAIL"
        print(f"[{status}] {result.name}: {result.detail}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the Limes Axis container release supply-chain baseline."
    )
    parser.add_argument(
        "--repo-root",
        default=Path(__file__).resolve().parents[3],
        type=Path,
        help="Repository root. Defaults to the current limes-axis checkout.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args()

    results = run_static_checks(args.repo_root)
    _print_results(results, json_output=args.json)
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
