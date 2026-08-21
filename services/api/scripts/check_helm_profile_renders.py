from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import NamedTuple


class ProfileRenderContract(NamedTuple):
    tenancy_mode: str
    network_mode: str
    profile: str


class RenderCheckResult(NamedTuple):
    name: str
    ok: bool
    detail: str


PROFILE_RENDER_CONTRACTS: dict[str, ProfileRenderContract] = {
    "infra/helm/limes-axis/profiles/single-tenant-managed.yaml": ProfileRenderContract(
        tenancy_mode="single_tenant_managed",
        network_mode="restricted",
        profile="single-tenant-managed",
    ),
    "infra/helm/limes-axis/profiles/private-cloud.yaml": ProfileRenderContract(
        tenancy_mode="private_cloud",
        network_mode="restricted",
        profile="private-cloud",
    ),
    "infra/helm/limes-axis/profiles/on-prem-offline.yaml": ProfileRenderContract(
        tenancy_mode="on_prem",
        network_mode="offline",
        profile="on-prem-offline",
    ),
}

FORBIDDEN_RENDER_SECRET_TERMS = (
    "REPLACE_WITH_EXTERNAL_SECRET_MANAGER_VALUE",
)


def _profile_render_terms(contract: ProfileRenderContract) -> tuple[str, ...]:
    return (
        "kind: Deployment",
        "app.kubernetes.io/component: api",
        "app.kubernetes.io/component: web",
        "kind: ExternalSecret",
        "external-secrets.io/v1",
        "kind: HorizontalPodAutoscaler",
        "kind: PodDisruptionBudget",
        "kind: NetworkPolicy",
        f"limes-axis.io/profile: {contract.profile}",
        f'AXIS_DEPLOYMENT_TENANCY_MODE: "{contract.tenancy_mode}"',
        f'AXIS_DEPLOYMENT_NETWORK_EGRESS_MODE: "{contract.network_mode}"',
        'AXIS_TENANT_ADMISSION_MODE: "registered_only"',
        'AXIS_DEPLOYMENT_CUSTOMER_ISOLATION_CONFIGURED: "false"',
        'AXIS_DEPLOYMENT_DATA_RESIDENCY_CONFIGURED: "false"',
        'AXIS_DEPLOYMENT_OPERATOR_ACCESS_RUNBOOK_CONFIGURED: "false"',
        'AXIS_DEPLOYMENT_BREAK_GLASS_APPROVAL_CONFIGURED: "false"',
        'AXIS_OIDC_AUTH_REQUIRED: "true"',
        'AXIS_OIDC_SESSION_COOKIE_SECURE: "true"',
        'AXIS_EXTERNAL_MODEL_EGRESS_ENABLED: "false"',
        'AXIS_CONNECTOR_SYNC_EXECUTION_ENABLED: "false"',
    )


def _missing_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if term not in text]


def _forbidden_secret_terms(text: str) -> list[str]:
    normalized = f"\n{text.replace('\r\n', '\n')}\n"
    forbidden = [term for term in FORBIDDEN_RENDER_SECRET_TERMS if term in text]
    if "\nkind: Secret\n" in normalized:
        forbidden.append("kind: Secret")
    return forbidden


def _render_profile(
    repo_root: Path,
    relative_profile: str,
    *,
    helm_binary: str,
) -> RenderCheckResult:
    chart_dir = repo_root / "infra" / "helm" / "limes-axis"
    profile_path = repo_root / relative_profile
    contract = PROFILE_RENDER_CONTRACTS[relative_profile]
    command = [
        helm_binary,
        "template",
        "limes-axis",
        str(chart_dir),
        "-f",
        str(profile_path),
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
        )
    except FileNotFoundError:
        return RenderCheckResult(
            f"deployment.profile_render.{contract.profile}",
            False,
            f"Helm binary not found: {helm_binary}",
        )

    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "helm template failed"
        return RenderCheckResult(
            f"deployment.profile_render.{contract.profile}",
            False,
            detail,
        )

    forbidden_secret_terms = _forbidden_secret_terms(completed.stdout)
    if forbidden_secret_terms:
        return RenderCheckResult(
            f"deployment.profile_render.{contract.profile}",
            False,
            "rendered manifest contains forbidden secret material: "
            f"{', '.join(forbidden_secret_terms)}",
        )

    missing = _missing_terms(completed.stdout, _profile_render_terms(contract))
    return RenderCheckResult(
        f"deployment.profile_render.{contract.profile}",
        not missing,
        "profile overlay renders the expected Kubernetes deployment contract"
        if not missing
        else f"rendered manifest missing required terms: {', '.join(missing)}",
    )


def run_render_checks(
    repo_root: Path,
    *,
    helm_binary: str = "helm",
) -> list[RenderCheckResult]:
    repo_root = repo_root.resolve()
    return [
        _render_profile(repo_root, relative_profile, helm_binary=helm_binary)
        for relative_profile in PROFILE_RENDER_CONTRACTS
    ]


def _print_results(results: list[RenderCheckResult], *, json_output: bool) -> None:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render Helm deployment profiles and verify public-safe contracts."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[3],
        help="Repository root to inspect.",
    )
    parser.add_argument(
        "--helm-binary",
        default="helm",
        help="Helm binary to execute.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    results = run_render_checks(args.repo_root, helm_binary=args.helm_binary)
    _print_results(results, json_output=args.json)
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
