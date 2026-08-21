from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT = REPO_ROOT / "services" / "api" / "scripts" / "check_helm_profile_renders.py"


def load_render_module():
    assert CHECK_SCRIPT.exists(), "Helm profile render checker is missing"
    spec = importlib.util.spec_from_file_location("check_helm_profile_renders", CHECK_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rendered_manifest(*, profile: str, tenancy_mode: str, egress_mode: str) -> str:
    return f"""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: limes-axis-api
  annotations:
    limes-axis.io/profile: {profile}
  labels:
    app.kubernetes.io/component: api
spec:
  template:
    metadata:
      annotations:
        limes-axis.io/profile: {profile}
    spec:
      containers:
        - name: api
          env:
            - name: AXIS_DEPLOYMENT_TENANCY_MODE
              value: {tenancy_mode}
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: limes-axis-config
data:
  AXIS_TENANT_ADMISSION_MODE: "registered_only"
  AXIS_DEPLOYMENT_TENANCY_MODE: "{tenancy_mode}"
  AXIS_DEPLOYMENT_NETWORK_EGRESS_MODE: "{egress_mode}"
  AXIS_EXTERNAL_MODEL_EGRESS_ENABLED: "false"
  AXIS_CONNECTOR_SYNC_EXECUTION_ENABLED: "false"
  AXIS_OIDC_AUTH_REQUIRED: "true"
  AXIS_OIDC_SESSION_COOKIE_SECURE: "true"
  AXIS_DEPLOYMENT_CUSTOMER_ISOLATION_CONFIGURED: "false"
  AXIS_DEPLOYMENT_DATA_RESIDENCY_CONFIGURED: "false"
  AXIS_DEPLOYMENT_OPERATOR_ACCESS_RUNBOOK_CONFIGURED: "false"
  AXIS_DEPLOYMENT_BREAK_GLASS_APPROVAL_CONFIGURED: "false"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: limes-axis-web
  annotations:
    limes-axis.io/profile: {profile}
  labels:
    app.kubernetes.io/component: web
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: limes-axis
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: limes-axis-api
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: limes-axis-api
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: limes-axis
spec:
  podSelector: {{}}
  policyTypes:
    - Egress
  egress:
    - to:
        - namespaceSelector: {{}}
# rendered egressMode: {egress_mode}
"""


def test_profile_render_checker_invokes_helm_template_for_every_profile(monkeypatch) -> None:
    checker = load_render_module()
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs):
        calls.append(command)
        profile_path = Path(command[-1])
        contract = checker.PROFILE_RENDER_CONTRACTS[str(profile_path.relative_to(REPO_ROOT))]
        return subprocess.CompletedProcess(
            command,
            0,
            rendered_manifest(
                profile=contract.profile,
                tenancy_mode=contract.tenancy_mode,
                egress_mode=contract.network_mode,
            ),
            "",
        )

    monkeypatch.setattr(checker.subprocess, "run", fake_run)

    results = checker.run_render_checks(REPO_ROOT, helm_binary="helm")

    assert [result.ok for result in results] == [True, True, True]
    assert len(calls) == 3
    for command in calls:
        assert command[:3] == ["helm", "template", "limes-axis"]
        assert str(REPO_ROOT / "infra" / "helm" / "limes-axis") in command
        assert "-f" in command
        assert command[-1].startswith(str(REPO_ROOT / "infra" / "helm" / "limes-axis" / "profiles"))


def test_profile_render_checker_rejects_missing_contract_terms(monkeypatch) -> None:
    checker = load_render_module()

    def fake_run(command: list[str], **kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            "kind: Deployment\nmetadata:\n  name: limes-axis-api\n",
            "",
        )

    monkeypatch.setattr(checker.subprocess, "run", fake_run)

    results = checker.run_render_checks(REPO_ROOT, helm_binary="helm")

    assert len(results) == 3
    assert all(not result.ok for result in results)
    assert all("rendered manifest missing required terms" in result.detail for result in results)


def test_profile_render_checker_rejects_rendered_local_secret_material(monkeypatch) -> None:
    checker = load_render_module()

    def fake_run(command: list[str], **kwargs):
        profile_path = Path(command[-1])
        contract = checker.PROFILE_RENDER_CONTRACTS[str(profile_path.relative_to(REPO_ROOT))]
        manifest = (
            rendered_manifest(
                profile=contract.profile,
                tenancy_mode=contract.tenancy_mode,
                egress_mode=contract.network_mode,
            )
            + """
---
apiVersion: v1
kind: Secret
metadata:
  name: limes-axis-runtime
stringData:
  AXIS_POSTGRES_DSN: REPLACE_WITH_EXTERNAL_SECRET_MANAGER_VALUE
"""
        )
        return subprocess.CompletedProcess(command, 0, manifest, "")

    monkeypatch.setattr(checker.subprocess, "run", fake_run)

    results = checker.run_render_checks(REPO_ROOT, helm_binary="helm")

    assert len(results) == 3
    assert all(not result.ok for result in results)
    assert all(
        "rendered manifest contains forbidden secret material" in result.detail
        for result in results
    )


def test_profile_render_checker_reports_missing_helm_binary(monkeypatch) -> None:
    checker = load_render_module()

    def fake_run(command: list[str], **kwargs):
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(checker.subprocess, "run", fake_run)

    results = checker.run_render_checks(REPO_ROOT, helm_binary="not-helm")

    assert len(results) == 3
    assert all(not result.ok for result in results)
    assert all("Helm binary not found" in result.detail for result in results)
