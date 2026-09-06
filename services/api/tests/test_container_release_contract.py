from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT = REPO_ROOT / "services" / "api" / "scripts" / "check_container_release.py"


def load_check_module():
    assert CHECK_SCRIPT.exists(), "container release checker is missing"
    spec = importlib.util.spec_from_file_location("check_container_release", CHECK_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_container_release_static_contract_passes() -> None:
    checker = load_check_module()

    results = checker.run_static_checks(REPO_ROOT)

    failures = [f"{result.name}: {result.detail}" for result in results if not result.ok]
    assert failures == []


def test_container_release_workflow_declares_supply_chain_boundaries() -> None:
    checker = load_check_module()

    required_terms = checker.required_workflow_terms()

    assert "ghcr.io/${{ github.repository_owner }}/limes-axis-api" in required_terms
    assert "ghcr.io/${{ github.repository_owner }}/limes-axis-web" in required_terms
    assert "docker/build-push-action@v7.3.0" in required_terms
    assert "actions/attest-build-provenance@v4.2.2" in required_terms
    assert "sigstore/cosign-installer@v4.1.2" in required_terms
    assert "sbom: true" in required_terms
    assert "provenance: mode=max" in required_terms
    assert "cosign sign --yes" in required_terms


def test_container_release_workflow_requires_promotion_and_rollback_evidence() -> None:
    checker = load_check_module()

    required_terms = checker.required_workflow_terms()

    assert "release_approval_issue" in required_terms
    assert "rollback_plan_issue" in required_terms
    assert "rollback_drill_id" in required_terms
    assert "rollback_plan_acknowledged" in required_terms
    assert "Validate promotion evidence" in required_terms
    assert "gh issue view \"$RELEASE_APPROVAL_ISSUE\"" in required_terms
    assert "gh issue view \"$ROLLBACK_PLAN_ISSUE\"" in required_terms
    assert (
        "push: ${{ github.event_name == 'workflow_dispatch' && inputs.push == true }}"
        in required_terms
    )


def test_container_release_publish_uses_dedicated_github_environment() -> None:
    checker = load_check_module()

    required_terms = checker.required_workflow_terms()

    assert "build-images:" in required_terms
    assert "publish-images:" in required_terms
    assert "needs: build-images" in required_terms
    assert "name: axis-container-release" in required_terms
    assert "GitHub Environment reviewer protection" in checker.required_docs_terms()


def test_container_release_permissions_are_keyless_and_registry_scoped() -> None:
    checker = load_check_module()

    required_permissions = checker.required_workflow_permissions()

    assert "contents: read" in required_permissions
    assert "packages: write" in required_permissions
    assert "id-token: write" in required_permissions
    assert "attestations: write" in required_permissions


def test_container_release_docs_track_remaining_enterprise_gaps() -> None:
    checker = load_check_module()

    required_terms = checker.required_docs_terms()

    assert "container-release-check" in required_terms
    assert "keyless signing" in required_terms
    assert "SBOM" in required_terms
    assert "release approval issue" in required_terms
    assert "rollback plan issue" in required_terms
    assert "rollback drill" in required_terms
    assert "not a production certification" in required_terms
