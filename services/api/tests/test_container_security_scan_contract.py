from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT = REPO_ROOT / "services" / "api" / "scripts" / "check_container_security_scan.py"


def load_check_module():
    assert CHECK_SCRIPT.exists(), "container security scan checker is missing"
    spec = importlib.util.spec_from_file_location("check_container_security_scan", CHECK_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_container_security_scan_static_contract_passes() -> None:
    checker = load_check_module()

    results = checker.run_static_checks(REPO_ROOT)

    failures = [f"{result.name}: {result.detail}" for result in results if not result.ok]
    assert failures == []


def test_container_security_scan_workflow_builds_and_scans_both_images() -> None:
    checker = load_check_module()

    terms = checker.required_workflow_terms()

    assert "aquasecurity/trivy-action" not in " ".join(terms)
    assert "ed142fd0673e97e23eac54620cfb913e5ce36c25" in terms
    assert "version: v0.71.2" in terms
    assert "image-ref: limes-axis-${{ matrix.component }}:scan" in terms
    assert "severity: CRITICAL" in terms
    assert "ignore-unfixed: true" in terms
    assert "continue-on-error: true" in terms
    assert "exit-code: \"1\"" in terms
    build_command = (
        "docker build -f ${{ matrix.dockerfile }} "
        "-t limes-axis-${{ matrix.component }}:scan ."
    )
    assert build_command in terms


def test_container_security_scan_has_scoped_code_scanning_permissions() -> None:
    checker = load_check_module()

    permissions = checker.required_workflow_permissions()

    assert permissions == ("contents: read", "security-events: write")


def test_container_security_scan_docs_record_local_real_scan_command() -> None:
    checker = load_check_module()

    docs_terms = checker.required_docs_terms()

    assert "make container-scan-local" in docs_terms
    assert ".axis/trivy-reports" in docs_terms
    assert "CRITICAL" in docs_terms
    assert "ignore-unfixed" in docs_terms
    assert "not a production certification" in docs_terms


def test_container_security_scan_local_target_matches_workflow_policy() -> None:
    checker = load_check_module()

    local_terms = checker.required_local_scan_terms()

    assert "--scanners vuln" in local_terms
    assert "--pkg-types os,library" in local_terms
    assert "--severity CRITICAL" in local_terms
    assert "--ignore-unfixed" in local_terms
    assert "--format json" in local_terms
    assert "--output /reports/api-critical.json" in local_terms
    assert "--output /reports/web-critical.json" in local_terms
    assert "limes-axis-api:local" in local_terms
    assert "limes-axis-web:local" in local_terms
