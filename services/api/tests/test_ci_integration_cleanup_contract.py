from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_live_integration_job_stops_background_api_before_post_hooks() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    integration = workflow.split("\n  integration:\n", maxsplit=1)[1].split(
        "\n  python:\n", maxsplit=1
    )[0]

    start = integration.index("      - name: Start API")
    failure_log = integration.index("      - name: API log on failure")
    stop = integration.index("      - name: Stop API")

    assert start < failure_log < stop
    assert 'echo "$!" > "${RUNNER_TEMP}/api.pid"' in integration
    assert "        if: always()" in integration[stop:]
    assert 'kill "${api_pid}" 2>/dev/null || true' in integration[stop:]
    assert 'kill -0 "${api_pid}" 2>/dev/null' in integration[stop:]
