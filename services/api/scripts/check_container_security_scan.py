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
    return (".github/workflows/container-security.yml",)


def required_workflow_permissions() -> tuple[str, ...]:
    return (
        "contents: read",
        "security-events: write",
    )


def required_workflow_terms() -> tuple[str, ...]:
    return (
        "pull_request:",
        "push:",
        "workflow_dispatch:",
        "services/api/Dockerfile",
        "apps/web/Dockerfile",
        "services/worker/Dockerfile",
        "docker build -f ${{ matrix.dockerfile }} -t limes-axis-${{ matrix.component }}:scan .",
        "ed142fd0673e97e23eac54620cfb913e5ce36c25",
        "version: v0.71.2",
        "scan-type: image",
        "image-ref: limes-axis-${{ matrix.component }}:scan",
        "severity: CRITICAL",
        "ignore-unfixed: true",
        "vuln-type: os,library",
        "scanners: vuln",
        "continue-on-error: true",
        "exit-code: \"1\"",
    )


def forbidden_workflow_terms() -> tuple[str, ...]:
    return (
        "packages: write",
        "id-token: write",
        "aquasecurity/trivy-action@v0.",
    )


def required_docs_terms() -> tuple[str, ...]:
    return (
        "make container-security-check",
        "make container-scan-local",
        ".axis/trivy-reports",
        "CRITICAL",
        "ignore-unfixed",
        "pinned to the v0.36.0 commit",
        "not a production certification",
    )


def required_local_scan_terms() -> tuple[str, ...]:
    return (
        "mkdir -p .axis/trivy-cache .axis/trivy-reports",
        "aquasec/trivy:0.71.2",
        "--scanners vuln",
        "--pkg-types os,library",
        "--severity CRITICAL",
        "--ignore-unfixed",
        "--exit-code 1",
        "--format json",
        "--output /reports/api-critical.json",
        "--output /reports/web-critical.json",
        "limes-axis-api:local",
        "limes-axis-web:local",
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


def _present_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    normalized = text.casefold()
    return [term for term in terms if term.casefold() in normalized]


def check_workflow_file(repo_root: Path) -> list[CheckResult]:
    missing = [
        relative for relative in required_workflow_files() if not (repo_root / relative).exists()
    ]
    return [
        CheckResult(
            "container_security.workflow_file",
            not missing,
            "container security scan workflow is present"
            if not missing
            else f"missing: {', '.join(missing)}",
        )
    ]


def check_workflow_terms(repo_root: Path) -> list[CheckResult]:
    workflow = repo_root / ".github" / "workflows" / "container-security.yml"
    if not workflow.exists():
        return [
            CheckResult(
                "container_security.workflow_terms",
                False,
                "container-security.yml is missing.",
            )
        ]

    text = _read_text(workflow)
    missing = _missing_terms(text, required_workflow_terms())
    return [
        CheckResult(
            "container_security.workflow_terms",
            not missing,
            "workflow builds and scans API and web images with a pinned Trivy action"
            if not missing
            else f"missing terms: {', '.join(missing)}",
        )
    ]


def check_workflow_permissions(repo_root: Path) -> list[CheckResult]:
    workflow = repo_root / ".github" / "workflows" / "container-security.yml"
    if not workflow.exists():
        return [
            CheckResult(
                "container_security.workflow_permissions",
                False,
                "container-security.yml is missing.",
            )
        ]

    text = _read_text(workflow)
    missing = _missing_terms(text, required_workflow_permissions())
    forbidden = _present_terms(text, forbidden_workflow_terms())
    ok = not missing and not forbidden
    if missing:
        detail = f"missing permissions: {', '.join(missing)}"
    elif forbidden:
        detail = f"unexpected privileged terms: {', '.join(forbidden)}"
    else:
        detail = "workflow uses read and code-scanning scoped repository permissions"
    return [CheckResult("container_security.workflow_permissions", ok, detail)]


def check_make_targets(repo_root: Path) -> list[CheckResult]:
    makefile = repo_root / "Makefile"
    if not makefile.exists():
        return [CheckResult("container_security.make_targets", False, "Makefile is missing.")]

    required_targets = {"container-security-check", "container-scan-local"}
    targets = _make_targets(_read_text(makefile))
    missing = sorted(required_targets - targets)
    return [
        CheckResult(
            "container_security.make_targets",
            not missing,
            "container security Make targets are present"
            if not missing
            else f"missing targets: {', '.join(missing)}",
        )
    ]


def check_local_scan_target(repo_root: Path) -> list[CheckResult]:
    makefile = repo_root / "Makefile"
    if not makefile.exists():
        return [
            CheckResult(
                "container_security.local_scan_target",
                False,
                "Makefile is missing.",
            )
        ]

    text = _read_text(makefile)
    missing = _missing_terms(text, required_local_scan_terms())
    return [
        CheckResult(
            "container_security.local_scan_target",
            not missing,
            "local scan target mirrors the workflow vulnerability policy"
            if not missing
            else f"missing terms: {', '.join(missing)}",
        )
    ]


def check_ci_gate(repo_root: Path) -> list[CheckResult]:
    ci = repo_root / ".github" / "workflows" / "ci.yml"
    if not ci.exists():
        return [CheckResult("container_security.ci_gate", False, "CI workflow is missing.")]

    text = _read_text(ci)
    return [
        CheckResult(
            "container_security.ci_gate",
            "make container-security-check" in text,
            "CI runs the container security scan contract check"
            if "make container-security-check" in text
            else "CI does not run make container-security-check",
        )
    ]


def check_docs(repo_root: Path) -> list[CheckResult]:
    expectations = (
        (
            "container_security.deployment_docs",
            repo_root / "docs" / "deployment.md",
            required_docs_terms(),
        ),
        (
            "container_security.readme_link",
            repo_root / "README.md",
            ("container-security-check", "container-scan-local", "Trivy"),
        ),
        (
            "container_security.plan_tracking",
            repo_root / "plan.md",
            ("Add container vulnerability scanning policy baseline",),
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
                f"{path.name} documents the container security scan boundary"
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
    checks.extend(check_make_targets(repo_root))
    checks.extend(check_local_scan_target(repo_root))
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
        description="Validate the Limes Axis container security scanning baseline."
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
