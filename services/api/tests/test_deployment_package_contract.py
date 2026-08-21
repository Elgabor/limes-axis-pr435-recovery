from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT = REPO_ROOT / "services" / "api" / "scripts" / "check_deployment_package.py"


def load_check_module():
    assert CHECK_SCRIPT.exists(), "deployment package checker is missing"
    spec = importlib.util.spec_from_file_location("check_deployment_package", CHECK_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_deployment_package_static_contract_passes() -> None:
    checker = load_check_module()

    results = checker.run_static_checks(REPO_ROOT)

    failures = [f"{result.name}: {result.detail}" for result in results if not result.ok]
    assert failures == []


def test_default_chart_renders_complete_production_admission_configuration() -> None:
    chart = REPO_ROOT / "infra" / "helm" / "limes-axis"
    completed = subprocess.run(
        [
            "helm",
            "template",
            "axis",
            str(chart),
            "--set",
            "secrets.externalSecret.enabled=true",
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    rendered = completed.stdout
    for expected in (
        'AXIS_TENANT_ADMISSION_MODE: "registered_only"',
        'AXIS_API_RATE_LIMIT_ENABLED: "true"',
        'AXIS_API_RATE_LIMIT_BACKEND: "redis"',
        'AXIS_API_RATE_LIMIT_FAILURE_MODE: "closed"',
        'AXIS_API_RATE_LIMIT_PATHS: "[\\"*\\"]"',
        'AXIS_REDIS_TIMEOUT_SECONDS: "0.25"',
        'AXIS_READINESS_PROBE_TIMEOUT_SECONDS: "1.0"',
        'secretKey: "AXIS_REDIS_URL"',
    ):
        assert expected in rendered


def test_deployment_package_declares_critical_chart_files() -> None:
    checker = load_check_module()

    required_files = checker.required_chart_files()

    assert "infra/helm/limes-axis/Chart.yaml" in required_files
    assert "infra/helm/limes-axis/values.yaml" in required_files
    assert "infra/helm/limes-axis/values.schema.json" in required_files
    assert "infra/helm/limes-axis/templates/api-deployment.yaml" in required_files
    assert "infra/helm/limes-axis/templates/api-service.yaml" in required_files
    assert "infra/helm/limes-axis/templates/web-deployment.yaml" in required_files
    assert "infra/helm/limes-axis/templates/web-service.yaml" in required_files
    assert "infra/helm/limes-axis/templates/hpa.yaml" in required_files
    assert "infra/helm/limes-axis/templates/poddisruptionbudget.yaml" in required_files
    assert "infra/helm/limes-axis/templates/ingress.yaml" in required_files
    assert "infra/helm/limes-axis/templates/configmap.yaml" in required_files
    assert "infra/helm/limes-axis/templates/secret-example.yaml" in required_files
    assert "infra/helm/limes-axis/templates/externalsecret.yaml" in required_files
    assert "infra/helm/limes-axis/templates/networkpolicy.yaml" in required_files
    assert "infra/helm/limes-axis/templates/tests/smoke-test.yaml" in required_files
    assert "infra/helm/limes-axis/templates/NOTES.txt" in required_files


def test_deployment_package_declares_deployment_profile_overlays() -> None:
    checker = load_check_module()

    required_profiles = checker.required_profile_files()

    assert "infra/helm/limes-axis/profiles/single-tenant-managed.yaml" in required_profiles
    assert "infra/helm/limes-axis/profiles/private-cloud.yaml" in required_profiles
    assert "infra/helm/limes-axis/profiles/on-prem-offline.yaml" in required_profiles


def test_deployment_package_includes_first_tenant_bootstrap_in_api_image() -> None:
    checker = load_check_module()

    required_tools = checker.required_runtime_tools()
    results = checker.check_runtime_tools(REPO_ROOT)

    assert "services/api/src/axis_api/bootstrap_tenant.py" in required_tools
    assert all(result.ok for result in results), [result.detail for result in results]


def test_deployment_values_schema_declares_operational_enums() -> None:
    schema_path = REPO_ROOT / "infra" / "helm" / "limes-axis" / "values.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    properties = schema["properties"]
    api_env = properties["api"]["properties"]["env"]["properties"]
    network_policy = properties["networkPolicy"]["properties"]
    external_secret = properties["secrets"]["properties"]["externalSecret"]["properties"]

    assert api_env["AXIS_TENANT_ADMISSION_MODE"]["enum"] == [
        "claims_only",
        "registered_only",
    ]
    assert api_env["AXIS_DEPLOYMENT_TENANCY_MODE"]["enum"] == [
        "saas_multi_tenant",
        "single_tenant_managed",
        "private_cloud",
        "on_prem",
    ]
    assert api_env["AXIS_CONNECTOR_EXPORT_OBJECT_STORE_ADAPTER"]["enum"] == [
        "local_filesystem",
        "s3_compatible",
    ]
    assert network_policy["egressMode"]["enum"] == [
        "port_allowlist",
        "restricted",
        "offline",
    ]
    assert external_secret["secretStoreRef"]["properties"]["kind"]["enum"] == [
        "SecretStore",
        "ClusterSecretStore",
    ]
    assert external_secret["target"]["properties"]["creationPolicy"]["enum"] == [
        "Owner",
        "Orphan",
        "Merge",
        "None",
    ]


def test_deployment_values_schema_rejects_invalid_operational_modes(tmp_path: Path) -> None:
    invalid_cases = {
        "tenant-admission": (
            """
api:
  env:
    AXIS_TENANT_ADMISSION_MODE: allow_all
""",
            "/api/env/AXIS_TENANT_ADMISSION_MODE",
        ),
        "tenancy": (
            """
api:
  env:
    AXIS_DEPLOYMENT_TENANCY_MODE: unsupported_mode
""",
            "/api/env/AXIS_DEPLOYMENT_TENANCY_MODE",
        ),
        "egress": (
            """
networkPolicy:
  egressMode: internet
""",
            "/networkPolicy/egressMode",
        ),
        "secret-store": (
            """
secrets:
  externalSecret:
    secretStoreRef:
      kind: RemoteSecretStore
""",
            "/secrets/externalSecret/secretStoreRef/kind",
        ),
        "issuer": (
            """
ingress:
  certManager:
    issuerKind: ExternalIssuer
""",
            "/ingress/certManager/issuerKind",
        ),
        "object-store-adapter": (
            """
api:
  env:
    AXIS_CONNECTOR_EXPORT_OBJECT_STORE_ADAPTER: filesystem
""",
            "/api/env/AXIS_CONNECTOR_EXPORT_OBJECT_STORE_ADAPTER",
        ),
    }

    for case_name, (values_yaml, expected_path) in invalid_cases.items():
        invalid_values = tmp_path / f"{case_name}.yaml"
        invalid_values.write_text(values_yaml, encoding="utf-8")

        completed = subprocess.run(
            [
                "helm",
                "lint",
                str(REPO_ROOT / "infra" / "helm" / "limes-axis"),
                "-f",
                str(invalid_values),
            ],
            capture_output=True,
            check=False,
            text=True,
        )

        assert completed.returncode != 0, case_name
        output = f"{completed.stdout}\n{completed.stderr}"
        assert expected_path in output


def test_deployment_values_schema_accepts_documented_object_store_adapter(
    tmp_path: Path,
) -> None:
    documented_values = tmp_path / "documented-object-store-adapter.yaml"
    documented_values.write_text(
        """
api:
  env:
    AXIS_CONNECTOR_EXPORT_OBJECT_STORE_ADAPTER: local_filesystem
""",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "helm",
            "lint",
            str(REPO_ROOT / "infra" / "helm" / "limes-axis"),
            "-f",
            str(documented_values),
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, (
        f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
    )


def test_deployment_profile_overlays_pass_helm_lint() -> None:
    for relative_profile in (
        "infra/helm/limes-axis/profiles/single-tenant-managed.yaml",
        "infra/helm/limes-axis/profiles/private-cloud.yaml",
        "infra/helm/limes-axis/profiles/on-prem-offline.yaml",
    ):
        completed = subprocess.run(
            [
                "helm",
                "lint",
                str(REPO_ROOT / "infra" / "helm" / "limes-axis"),
                "-f",
                str(REPO_ROOT / relative_profile),
            ],
            capture_output=True,
            check=False,
            text=True,
        )

        assert completed.returncode == 0, (
            f"{relative_profile}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )


def test_deployment_package_validates_profile_overlay_contracts() -> None:
    checker = load_check_module()

    results = checker.check_profile_contracts(REPO_ROOT)

    failures = [f"{result.name}: {result.detail}" for result in results if not result.ok]
    assert failures == []


def test_deployment_profile_contract_rejects_false_evidence_and_secrets(
    tmp_path: Path,
) -> None:
    checker = load_check_module()
    for relative in checker.required_profile_files():
        source = REPO_ROOT / relative
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    unsafe_profile = (
        tmp_path
        / "infra"
        / "helm"
        / "limes-axis"
        / "profiles"
        / "single-tenant-managed.yaml"
    )
    unsafe_profile.write_text(
        unsafe_profile.read_text(encoding="utf-8").replace(
            'AXIS_DEPLOYMENT_CUSTOMER_ISOLATION_CONFIGURED: "false"',
            'AXIS_DEPLOYMENT_CUSTOMER_ISOLATION_CONFIGURED: "true"',
        )
        + "\nAXIS_OIDC_CLIENT_SECRET: hardcoded-secret\n",
        encoding="utf-8",
    )

    results = checker.check_profile_contracts(tmp_path)

    failures = [result.detail for result in results if not result.ok]
    assert len(failures) == 1
    assert "customer-specific evidence gates must remain false" in failures[0]
    assert "hardcoded secret material" in failures[0]


def test_deployment_package_declares_rollout_rehearsal_tooling() -> None:
    checker = load_check_module()

    assert (
        "services/api/scripts/check_helm_profile_renders.py"
        in checker.required_deployment_scripts()
    )
    assert (
        "services/api/scripts/rehearse_deployment_rollout.py"
        in checker.required_deployment_scripts()
    )
    assert (
        "services/api/scripts/rehearse_production_backup.py"
        in checker.required_deployment_scripts()
    )
    assert (
        "services/api/scripts/rehearse_production_restore.py"
        in checker.required_deployment_scripts()
    )
    assert (
        "services/api/scripts/rehearse_typedb_recovery.py"
        in checker.required_deployment_scripts()
    )
    assert (
        "services/api/scripts/rehearse_object_storage_recovery.py"
        in checker.required_deployment_scripts()
    )
    assert (
        "services/api/scripts/rehearse_temporal_recovery.py"
        in checker.required_deployment_scripts()
    )
    assert (
        "services/api/scripts/rehearse_secret_rotation.py"
        in checker.required_deployment_scripts()
    )
    assert (
        "services/api/scripts/rehearse_ha_restart.py"
        in checker.required_deployment_scripts()
    )
    assert "services/api/scripts/rehearse_load.py" in checker.required_deployment_scripts()
    assert (
        "services/api/scripts/rehearse_tls_readiness.py"
        in checker.required_deployment_scripts()
    )
    assert "deployment-profile-render-check" in checker.required_make_targets()
    assert "deployment-rollout-rehearsal-plan" in checker.required_make_targets()
    assert "deployment-rollout-rehearsal" in checker.required_make_targets()
    assert "deployment-backup-rehearsal-plan" in checker.required_make_targets()
    assert "deployment-backup-rehearsal" in checker.required_make_targets()
    assert "deployment-restore-rehearsal-plan" in checker.required_make_targets()
    assert "deployment-restore-rehearsal" in checker.required_make_targets()
    assert "deployment-typedb-recovery-rehearsal-plan" in checker.required_make_targets()
    assert "deployment-typedb-recovery-rehearsal" in checker.required_make_targets()
    assert "deployment-object-storage-recovery-rehearsal-plan" in checker.required_make_targets()
    assert "deployment-object-storage-recovery-rehearsal" in checker.required_make_targets()
    assert "deployment-temporal-recovery-rehearsal-plan" in checker.required_make_targets()
    assert "deployment-temporal-recovery-rehearsal" in checker.required_make_targets()
    assert "deployment-secret-rotation-rehearsal-plan" in checker.required_make_targets()
    assert "deployment-secret-rotation-rehearsal" in checker.required_make_targets()
    assert "deployment-ha-rehearsal-plan" in checker.required_make_targets()
    assert "deployment-ha-rehearsal" in checker.required_make_targets()
    assert "deployment-load-rehearsal-plan" in checker.required_make_targets()
    assert "deployment-load-rehearsal" in checker.required_make_targets()
    assert "deployment-tls-readiness-plan" in checker.required_make_targets()
    assert "deployment-tls-readiness" in checker.required_make_targets()


def test_deployment_package_externalizes_state_and_secrets() -> None:
    checker = load_check_module()

    required_terms = checker.required_chart_terms()

    assert "AXIS_POSTGRES_DSN" in required_terms
    assert "AXIS_TYPEDB_ADDRESS" in required_terms
    assert "AXIS_TEMPORAL_ADDRESS" in required_terms
    assert "AXIS_CONNECTOR_EXPORT_OBJECT_STORE_ROOT" in required_terms
    assert "AXIS_CONNECTOR_EXPORT_OBJECT_STORE_ADAPTER" in required_terms
    assert "AXIS_CONNECTOR_EXPORT_S3_ENDPOINT" in required_terms
    assert "AXIS_CONNECTOR_EXPORT_S3_BUCKET" in required_terms
    assert "AXIS_CONNECTOR_EXPORT_S3_ACCESS_KEY" in required_terms
    assert "AXIS_CONNECTOR_EXPORT_S3_SECRET_KEY" in required_terms
    assert "AXIS_CONNECTOR_EXPORT_S3_OBJECT_LOCK_ENABLED" in required_terms
    assert "AXIS_CONNECTOR_EXPORT_S3_RETENTION_DAYS" in required_terms
    assert "AXIS_DR_RUNBOOK_CONFIGURED" in required_terms
    assert "AXIS_DR_RPO_RTO_DEFINED" in required_terms
    assert "AXIS_DR_REHEARSAL_EVIDENCE_CONFIGURED" in required_terms
    assert "AXIS_DR_RESTORE_OWNER_CONFIGURED" in required_terms
    assert "AXIS_DR_CUSTOMER_APPROVAL_CONFIGURED" in required_terms
    assert "AXIS_DEPLOYMENT_NETWORK_POLICY_ENABLED" in required_terms
    assert "AXIS_DEPLOYMENT_NETWORK_EGRESS_MODE" in required_terms
    assert "AXIS_DEPLOYMENT_NETWORK_EGRESS_ALLOWLIST_CONFIGURED" in required_terms
    assert "AXIS_DEPLOYMENT_TENANCY_MODE" in required_terms
    assert "AXIS_DEPLOYMENT_CUSTOMER_ISOLATION_CONFIGURED" in required_terms
    assert "AXIS_DEPLOYMENT_DATA_RESIDENCY_CONFIGURED" in required_terms
    assert "AXIS_DEPLOYMENT_OPERATOR_ACCESS_RUNBOOK_CONFIGURED" in required_terms
    assert "AXIS_DEPLOYMENT_BREAK_GLASS_APPROVAL_CONFIGURED" in required_terms
    assert "AXIS_TENANT_ADMISSION_MODE" in required_terms
    assert "AXIS_OIDC_ISSUER" in required_terms
    assert "AXIS_OIDC_CLIENT_ID" in required_terms
    assert "AXIS_OIDC_CLIENT_SECRET" in required_terms
    assert "AXIS_OIDC_AUTHORIZATION_URL" in required_terms
    assert "AXIS_OIDC_TOKEN_URL" in required_terms
    assert "AXIS_OIDC_REDIRECT_URI" in required_terms
    assert "AXIS_OIDC_SESSION_COOKIE_SIGNING_SECRET" in required_terms
    assert "AXIS_OIDC_SESSION_COOKIE_TTL_SECONDS" in required_terms
    assert "AXIS_OIDC_SESSION_COOKIE_SECURE" in required_terms
    assert "AXIS_API_RATE_LIMIT_ENABLED" in required_terms
    assert "AXIS_API_RATE_LIMIT_REQUESTS" in required_terms
    assert "AXIS_API_RATE_LIMIT_WINDOW_SECONDS" in required_terms
    assert "AXIS_API_RATE_LIMIT_PATHS" in required_terms
    assert "AXIS_SUPPORT_MODEL_ENABLED" in required_terms
    assert "AXIS_SUPPORT_COVERAGE" in required_terms
    assert "AXIS_SUPPORT_S1_RESPONSE_MINUTES" in required_terms
    assert "AXIS_SUPPORT_ESCALATION_CHANNELS" in required_terms
    assert "AXIS_SUPPORT_CUSTOMER_RUNBOOK_URL" in required_terms
    assert "AXIS_SUPPORT_STATUS_PAGE_URL" in required_terms
    assert "AXIS_SUPPORT_INCIDENT_REVIEW_REQUIRED" in required_terms
    assert "AXIS_SUPPORT_SIGNED_COMMITMENT_CONFIGURED" in required_terms
    assert "AXIS_SUPPORT_NAMED_STAFFING_MODEL_CONFIGURED" in required_terms
    assert "AXIS_SUPPORT_CUSTOMER_INCIDENT_OPERATIONS_CONFIGURED" in required_terms
    assert "AXIS_SUPPORT_LEGAL_SLA_TERMS_CONFIGURED" in required_terms
    assert "values.schema.json" in required_terms
    assert "schema validation" in required_terms
    assert '"saas_multi_tenant"' in required_terms
    assert '"single_tenant_managed"' in required_terms
    assert '"private_cloud"' in required_terms
    assert '"on_prem"' in required_terms
    assert "existingSecret" in required_terms
    assert "REPLACE_WITH_EXTERNAL_SECRET_MANAGER_VALUE" in required_terms
    assert "ExternalSecret" in required_terms
    assert "external-secrets.io/v1" in required_terms
    assert "secretStoreRef" in required_terms
    assert "refreshPolicy" in required_terms
    assert "refreshInterval" in required_terms
    assert "creationPolicy" in required_terms
    assert "deletionPolicy" in required_terms
    assert "remoteRef" in required_terms
    assert "networking.k8s.io/v1" in required_terms
    assert "ingressClassName" in required_terms
    assert "tls:" in required_terms
    assert "pathType" in required_terms
    assert "certManager:" in required_terms
    assert "cert-manager.io/cluster-issuer" in required_terms
    assert "cert-manager.io/issuer-kind" in required_terms
    assert "cert-manager.io/issuer-group" in required_terms
    assert "autoscaling/v2" in required_terms
    assert "HorizontalPodAutoscaler" in required_terms
    assert "scaleTargetRef" in required_terms
    assert "averageUtilization" in required_terms
    assert "policy/v1" in required_terms
    assert "PodDisruptionBudget" in required_terms
    assert "minAvailable" in required_terms
    assert "nodeSelector" in required_terms
    assert "affinity" in required_terms
    assert "tolerations" in required_terms
    assert "topologySpreadConstraints" in required_terms
    assert "strategy:" in required_terms
    assert "rollingUpdate" in required_terms
    assert "maxUnavailable" in required_terms
    assert "maxSurge" in required_terms
    assert "revisionHistoryLimit" in required_terms
    assert "terminationGracePeriodSeconds" in required_terms
    assert "lifecycle:" in required_terms
    assert "helm.sh/hook" in required_terms
    assert "hook-delete-policy" in required_terms
    assert "tests:" in required_terms
    assert "smoke:" in required_terms
    assert "busybox" in required_terms
    assert "wget" in required_terms


def test_deployment_package_ha_controls_are_optional_and_target_api_and_web() -> None:
    values = (REPO_ROOT / "infra" / "helm" / "limes-axis" / "values.yaml").read_text(
        encoding="utf-8"
    )
    hpa_template = (
        REPO_ROOT / "infra" / "helm" / "limes-axis" / "templates" / "hpa.yaml"
    ).read_text(encoding="utf-8")
    pdb_template = (
        REPO_ROOT
        / "infra"
        / "helm"
        / "limes-axis"
        / "templates"
        / "poddisruptionbudget.yaml"
    ).read_text(encoding="utf-8")

    assert "autoscaling:" in values
    assert "pdb:" in values
    assert "{{- if .Values.api.autoscaling.enabled -}}" in hpa_template
    assert "{{- if .Values.web.autoscaling.enabled }}" in hpa_template
    assert "kind: HorizontalPodAutoscaler" in hpa_template
    assert "name: {{ include \"limes-axis.fullname\" . }}-api" in hpa_template
    assert "name: {{ include \"limes-axis.fullname\" . }}-web" in hpa_template
    assert "{{- if .Values.api.pdb.enabled -}}" in pdb_template
    assert "{{- if .Values.web.pdb.enabled }}" in pdb_template
    assert "kind: PodDisruptionBudget" in pdb_template
    assert "app.kubernetes.io/component: api" in pdb_template
    assert "app.kubernetes.io/component: web" in pdb_template


def test_network_policy_declares_restricted_and_offline_egress_modes() -> None:
    values = (REPO_ROOT / "infra" / "helm" / "limes-axis" / "values.yaml").read_text(
        encoding="utf-8"
    )
    network_policy = (
        REPO_ROOT
        / "infra"
        / "helm"
        / "limes-axis"
        / "templates"
        / "networkpolicy.yaml"
    ).read_text(encoding="utf-8")

    assert "egressMode: port_allowlist" in values
    assert "allowedEgressCidrs:" in values
    assert "restricted" in network_policy
    assert "offline" in network_policy
    assert "ipBlock:" in network_policy
    assert ".Values.networkPolicy.allowedEgressCidrs" in network_policy


def test_deployment_chart_declares_tenancy_profile_boundaries() -> None:
    values = (REPO_ROOT / "infra" / "helm" / "limes-axis" / "values.yaml").read_text(
        encoding="utf-8"
    )
    configmap = (
        REPO_ROOT / "infra" / "helm" / "limes-axis" / "templates" / "configmap.yaml"
    ).read_text(encoding="utf-8")

    assert "AXIS_DEPLOYMENT_TENANCY_MODE: saas_multi_tenant" in values
    assert "AXIS_TENANT_ADMISSION_MODE: registered_only" in values
    assert "single_tenant_managed" in values
    assert "private_cloud" in values
    assert "on_prem" in values
    assert "AXIS_DEPLOYMENT_CUSTOMER_ISOLATION_CONFIGURED" in values
    assert "AXIS_DEPLOYMENT_DATA_RESIDENCY_CONFIGURED" in values
    assert "AXIS_DEPLOYMENT_OPERATOR_ACCESS_RUNBOOK_CONFIGURED" in values
    assert "AXIS_DEPLOYMENT_BREAK_GLASS_APPROVAL_CONFIGURED" in values
    assert "AXIS_DEPLOYMENT_TENANCY_MODE" in configmap
    assert "AXIS_TENANT_ADMISSION_MODE" in configmap
    assert "AXIS_DEPLOYMENT_CUSTOMER_ISOLATION_CONFIGURED" in configmap
    assert "AXIS_DEPLOYMENT_DATA_RESIDENCY_CONFIGURED" in configmap
    assert "AXIS_DEPLOYMENT_OPERATOR_ACCESS_RUNBOOK_CONFIGURED" in configmap
    assert "AXIS_DEPLOYMENT_BREAK_GLASS_APPROVAL_CONFIGURED" in configmap


def test_deployment_profiles_are_safe_customer_specific_overlays() -> None:
    profile_dir = REPO_ROOT / "infra" / "helm" / "limes-axis" / "profiles"
    expected_modes = {
        "single-tenant-managed.yaml": "single_tenant_managed",
        "private-cloud.yaml": "private_cloud",
        "on-prem-offline.yaml": "on_prem",
    }

    for file_name, tenancy_mode in expected_modes.items():
        profile = (profile_dir / file_name).read_text(encoding="utf-8")
        assert "AXIS_TENANT_ADMISSION_MODE: registered_only" in profile
        assert f"AXIS_DEPLOYMENT_TENANCY_MODE: {tenancy_mode}" in profile
        assert "AXIS_DEPLOYMENT_CUSTOMER_ISOLATION_CONFIGURED: \"false\"" in profile
        assert "AXIS_DEPLOYMENT_DATA_RESIDENCY_CONFIGURED: \"false\"" in profile
        assert "AXIS_DEPLOYMENT_OPERATOR_ACCESS_RUNBOOK_CONFIGURED: \"false\"" in profile
        assert "AXIS_DEPLOYMENT_BREAK_GLASS_APPROVAL_CONFIGURED: \"false\"" in profile
        assert "AXIS_OIDC_AUTH_REQUIRED: \"true\"" in profile
        assert "AXIS_OIDC_SESSION_COOKIE_SECURE: \"true\"" in profile
        assert "externalSecret:" in profile
        assert "enabled: true" in profile
        assert "pdb:" in profile
        assert "autoscaling:" in profile
        assert "limes-axis.io/profile" in profile

    on_prem = (profile_dir / "on-prem-offline.yaml").read_text(encoding="utf-8")
    assert "egressMode: offline" in on_prem


def test_deployment_package_scheduling_controls_are_configurable_per_workload() -> None:
    values = (REPO_ROOT / "infra" / "helm" / "limes-axis" / "values.yaml").read_text(
        encoding="utf-8"
    )
    api_template = (
        REPO_ROOT / "infra" / "helm" / "limes-axis" / "templates" / "api-deployment.yaml"
    ).read_text(encoding="utf-8")
    web_template = (
        REPO_ROOT / "infra" / "helm" / "limes-axis" / "templates" / "web-deployment.yaml"
    ).read_text(encoding="utf-8")

    for field in (
        "nodeSelector:",
        "affinity:",
        "tolerations:",
        "topologySpreadConstraints:",
    ):
        assert field in values
        assert field in api_template
        assert field in web_template

    assert "{{- with .Values.api.nodeSelector }}" in api_template
    assert "{{- with .Values.api.affinity }}" in api_template
    assert "{{- with .Values.api.tolerations }}" in api_template
    assert "{{- with .Values.api.topologySpreadConstraints }}" in api_template
    assert "{{- with .Values.web.nodeSelector }}" in web_template
    assert "{{- with .Values.web.affinity }}" in web_template
    assert "{{- with .Values.web.tolerations }}" in web_template
    assert "{{- with .Values.web.topologySpreadConstraints }}" in web_template


def test_deployment_package_rollout_controls_are_configurable_per_workload() -> None:
    values = (REPO_ROOT / "infra" / "helm" / "limes-axis" / "values.yaml").read_text(
        encoding="utf-8"
    )
    api_template = (
        REPO_ROOT / "infra" / "helm" / "limes-axis" / "templates" / "api-deployment.yaml"
    ).read_text(encoding="utf-8")
    web_template = (
        REPO_ROOT / "infra" / "helm" / "limes-axis" / "templates" / "web-deployment.yaml"
    ).read_text(encoding="utf-8")

    for field in (
        "strategy:",
        "rollingUpdate:",
        "maxUnavailable:",
        "maxSurge:",
        "revisionHistoryLimit:",
        "terminationGracePeriodSeconds:",
        "lifecycle:",
    ):
        assert field in values
        assert field in api_template
        assert field in web_template

    assert "{{- with .Values.api.strategy }}" in api_template
    assert "revisionHistoryLimit: {{ .Values.api.revisionHistoryLimit }}" in api_template
    assert (
        "terminationGracePeriodSeconds: {{ .Values.api.terminationGracePeriodSeconds }}"
        in api_template
    )
    assert "{{- with .Values.api.lifecycle }}" in api_template
    assert "{{- with .Values.web.strategy }}" in web_template
    assert "revisionHistoryLimit: {{ .Values.web.revisionHistoryLimit }}" in web_template
    assert (
        "terminationGracePeriodSeconds: {{ .Values.web.terminationGracePeriodSeconds }}"
        in web_template
    )
    assert "{{- with .Values.web.lifecycle }}" in web_template


def test_deployment_package_helm_smoke_test_checks_api_and_web_services() -> None:
    values = (REPO_ROOT / "infra" / "helm" / "limes-axis" / "values.yaml").read_text(
        encoding="utf-8"
    )
    template = (
        REPO_ROOT
        / "infra"
        / "helm"
        / "limes-axis"
        / "templates"
        / "tests"
        / "smoke-test.yaml"
    ).read_text(encoding="utf-8")
    network_policy = (
        REPO_ROOT / "infra" / "helm" / "limes-axis" / "templates" / "networkpolicy.yaml"
    ).read_text(encoding="utf-8")

    for field in (
        "tests:",
        "smoke:",
        "enabled: true",
        "activeDeadlineSeconds:",
        "retryAttempts:",
        "requestTimeoutSeconds:",
        "podSecurityContext:",
        "securityContext:",
    ):
        assert field in values

    assert "{{- if .Values.tests.smoke.enabled -}}" in template
    assert "helm.sh/hook: test" in template
    assert "helm.sh/hook-delete-policy:" in template
    assert "image: {{ include \"limes-axis.smokeTestImage\" . | quote }}" in template
    assert "wget -q -O /dev/null" in template
    assert "{{ include \"limes-axis.fullname\" . }}-api" in template
    assert "{{ include \"limes-axis.fullname\" . }}-web" in template
    assert "/ready" in template
    assert "restartPolicy: Never" in template
    assert "{{- if .Values.tests.smoke.enabled }}" in network_policy
    assert "port: {{ .Values.api.service.port }}" in network_policy
    assert "port: {{ .Values.web.service.port }}" in network_policy


def test_deployment_package_ingress_is_optional_and_routes_api_and_web() -> None:
    values = (REPO_ROOT / "infra" / "helm" / "limes-axis" / "values.yaml").read_text(
        encoding="utf-8"
    )
    template = (
        REPO_ROOT / "infra" / "helm" / "limes-axis" / "templates" / "ingress.yaml"
    ).read_text(encoding="utf-8")

    assert "ingress:" in values
    assert "enabled: false" in values
    assert "{{- if .Values.ingress.enabled -}}" in template
    assert "apiVersion: networking.k8s.io/v1" in template
    assert "ingressClassName:" in template
    assert "secretName:" in template
    assert "name: {{ include \"limes-axis.fullname\" $ }}-api" in template
    assert "name: {{ include \"limes-axis.fullname\" $ }}-web" in template


def test_deployment_package_cert_manager_ingress_shim_is_optional() -> None:
    values = (REPO_ROOT / "infra" / "helm" / "limes-axis" / "values.yaml").read_text(
        encoding="utf-8"
    )
    template = (
        REPO_ROOT / "infra" / "helm" / "limes-axis" / "templates" / "ingress.yaml"
    ).read_text(encoding="utf-8")

    assert "certManager:" in values
    assert "enabled: false" in values
    assert "issuerName:" in values
    assert "issuerKind: ClusterIssuer" in values
    assert "issuerGroup: cert-manager.io" in values
    assert "{{- if .Values.ingress.certManager.enabled }}" in template
    assert (
        "required \"ingress.certManager.issuerName is required when certManager is enabled\""
        in template
    )
    assert "cert-manager.io/cluster-issuer:" in template
    assert "cert-manager.io/issuer:" in template
    assert "cert-manager.io/issuer-kind:" in template
    assert "cert-manager.io/issuer-group:" in template


def test_deployment_package_external_secret_is_optional_and_targets_runtime_secret() -> None:
    values = (REPO_ROOT / "infra" / "helm" / "limes-axis" / "values.yaml").read_text(
        encoding="utf-8"
    )
    template = (
        REPO_ROOT / "infra" / "helm" / "limes-axis" / "templates" / "externalsecret.yaml"
    ).read_text(encoding="utf-8")

    assert "externalSecret:" in values
    assert "enabled: false" in values
    assert "{{- if .Values.secrets.externalSecret.enabled -}}" in template
    assert "name: {{ .Values.secrets.existingSecret | quote }}" in template
    assert "secretStoreRef:" in template
    assert "remoteRef:" in template


def test_deployment_docs_are_public_safe_and_do_not_claim_certification() -> None:
    checker = load_check_module()

    required_terms = checker.required_docs_terms()

    assert "helm upgrade --install" in required_terms
    assert "external Postgres" in required_terms
    assert "OIDC" in required_terms
    assert "authorization-code" in required_terms
    assert "HTTP-only" in required_terms
    assert "rate limiting" in required_terms
    assert "IdP onboarding" in required_terms
    assert "/identity/oidc/onboarding" in required_terms
    assert "/identity/oidc/logout" in required_terms
    assert "/identity/session/logout" in required_terms
    assert "oidc_browser_sessions" in required_terms
    assert "server-side session revocation" in required_terms
    assert "AXIS_OIDC_CLIENT_ID" in required_terms
    assert "AXIS_OIDC_END_SESSION_URL" in required_terms
    assert "AXIS_OIDC_POST_LOGOUT_REDIRECT_URI" in required_terms
    assert "AXIS_OIDC_SESSION_COOKIE_SIGNING_SECRET" in required_terms
    assert "AXIS_OIDC_SESSION_COOKIE_TTL_SECONDS" in required_terms
    assert "AXIS_OIDC_SESSION_COOKIE_SECURE=true" in required_terms
    assert "oidc_secure_cookie_session" in required_terms
    assert "bounded TTL" in required_terms
    assert "HTTPS API/public/redirect URLs" in required_terms
    assert "S3-compatible object storage" in required_terms
    assert "External Secrets Operator" in required_terms
    assert "cert-manager" in required_terms
    assert "HorizontalPodAutoscaler" in required_terms
    assert "PodDisruptionBudget" in required_terms
    assert "topologySpreadConstraints" in required_terms
    assert "RollingUpdate" in required_terms
    assert "terminationGracePeriodSeconds" in required_terms
    assert "helm template" in required_terms
    assert "deployment-profile-render-check" in required_terms
    assert "profile render gate" in required_terms
    assert "deployment-rollout-rehearsal" in required_terms
    assert "kubectl rollout status" in required_terms
    assert "helm rollback" in required_terms
    assert "helm test" in required_terms
    assert "production backup rehearsal" in required_terms
    assert "production restore rehearsal" in required_terms
    assert "TypeDB recovery rehearsal" in required_terms
    assert "pg_dump" in required_terms
    assert "pg_restore --list" in required_terms
    assert "AXIS_POSTGRES_RESTORE_DSN" in required_terms
    assert "AXIS_TYPEDB_RESTORE_DATABASE" in required_terms
    assert "database export" in required_terms
    assert "database import" in required_terms
    assert "object storage recovery rehearsal" in required_terms
    assert "AXIS_CONNECTOR_EXPORT_S3_RESTORE_BUCKET" in required_terms
    assert "AXIS_OBJECT_STORAGE_RECOVERY_IMAGE" in required_terms
    assert "mc alias set" in required_terms
    assert "mc cp" in required_terms
    assert "mc cat" in required_terms
    assert "Temporal recovery rehearsal" in required_terms
    assert "AXIS_TEMPORAL_RECOVERY_IMAGE" in required_terms
    assert "AXIS_TEMPORAL_RECOVERY_WORKFLOW_ID" in required_terms
    assert "operator namespace describe" in required_terms
    assert "workflow show --output json" in required_terms
    assert "secret rotation rehearsal" in required_terms
    assert "AXIS_SECRET_ROTATION_IMAGE" in required_terms
    assert "limes-axis.io/secret-rotation-target=staged" in required_terms
    assert "secret-rotation.summary.json" in required_terms
    assert "secret-rotation.sha256" in required_terms
    assert "HA restart rehearsal" in required_terms
    assert "deployment-ha-rehearsal-plan" in required_terms
    assert "kubectl rollout restart" in required_terms
    assert "kubectl wait --for=condition=available" in required_terms
    assert "load rehearsal" in required_terms
    assert "deployment-load-rehearsal-plan" in required_terms
    assert "fortio" in required_terms
    assert "kubectl create job" in required_terms
    assert "kubectl logs" in required_terms
    assert "TLS readiness rehearsal" in required_terms
    assert "deployment-tls-readiness-plan" in required_terms
    assert "openssl s_client" in required_terms
    assert "dig +short" in required_terms
    assert "kubectl wait --for=condition=Ready" in required_terms
    assert "support-readiness" in required_terms
    assert "AXIS_SUPPORT_MODEL_ENABLED" in required_terms
    assert "AXIS_SUPPORT_ESCALATION_CHANNELS" in required_terms
    assert "AXIS_SUPPORT_SIGNED_COMMITMENT_CONFIGURED" in required_terms
    assert "AXIS_SUPPORT_NAMED_STAFFING_MODEL_CONFIGURED" in required_terms
    assert "AXIS_SUPPORT_CUSTOMER_INCIDENT_OPERATIONS_CONFIGURED" in required_terms
    assert "AXIS_SUPPORT_LEGAL_SLA_TERMS_CONFIGURED" in required_terms
    assert "production_support_commitments" in required_terms
    assert "/ready" in required_terms
    assert "not a production certification" in required_terms
