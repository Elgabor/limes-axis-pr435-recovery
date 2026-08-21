"""Production workflow-history persistence for API signal paths.

The persistence layer already knows how to update workflow runs and append
timeline events (``record_workflow_action_run``, ``record_workflow_action_run_outcome``
and ``record_workflow_approval_decision``), but those updaters no-op when no
``workflow_runs`` row exists for the signalled workflow. Nothing in production
ever created that row, so fresh deployments never accumulate replay history.

This module closes that gap: behind ``AXIS_WORKFLOW_HISTORY_PERSISTENCE_ENABLED``
the API signal paths call :func:`ensure_workflow_run` before recording a
workflow update, bootstrapping the run record from the tenant's persisted
workflow console reference. History rows are written in the same repository
session (and therefore the same transaction) as the primary record.
"""

from datetime import datetime

from axis_api.demo import WorkflowRun
from axis_api.manufacturing_metadata import ManufacturingTenantNotFound
from axis_api.models import WorkflowRunRecord
from axis_api.persistence import AxisPersistenceRepository, WorkflowRunCreate
from axis_api.workflow_reference import (
    WorkflowReferenceRecordInvalid,
    WorkflowReferenceRecordNotFound,
    get_persisted_manufacturing_workflow_console,
)


class WorkflowHistoryBootstrapError(ValueError):
    """The workflow console reference run cannot seed a persisted run record."""


def ensure_workflow_run(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    workflow_id: str,
) -> WorkflowRunRecord | None:
    """Return the persisted workflow run for a signalled workflow.

    When the run does not exist yet, it is bootstrapped from the tenant's
    persisted workflow console reference record so subsequent signal updates
    (action runs, approval decisions, outcomes) accumulate real, replayable
    history. Returns ``None`` when the workflow is not defined in the
    reference record: unknown workflow ids keep today's no-history behavior
    and never block the primary operation.
    """
    existing = repository.get_workflow_run(tenant_id, workflow_id)
    if existing is not None:
        return existing

    reference_run = _reference_workflow_run(repository, tenant_id, workflow_id)
    if reference_run is None:
        return None

    return repository.create_workflow_run(_bootstrap_workflow_run(tenant_id, reference_run))


def _reference_workflow_run(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    workflow_id: str,
) -> WorkflowRun | None:
    try:
        console = get_persisted_manufacturing_workflow_console(repository, tenant_id=tenant_id)
    except (
        ManufacturingTenantNotFound,
        WorkflowReferenceRecordNotFound,
        WorkflowReferenceRecordInvalid,
    ):
        return None

    for run in console.workflow_runs:
        if run.workflow_id == workflow_id:
            return run
    return None


def _bootstrap_workflow_run(tenant_id: str, run: WorkflowRun) -> WorkflowRunCreate:
    try:
        started_at = datetime.fromisoformat(run.started_at)
    except ValueError as exc:
        raise WorkflowHistoryBootstrapError(
            f"Workflow console reference run {run.workflow_id} has an invalid "
            "started_at timestamp"
        ) from exc

    return WorkflowRunCreate(
        tenant_id=tenant_id,
        workflow_id=run.workflow_id,
        name=run.name,
        domain=run.domain,
        state=run.state,
        status=run.status.value,
        owner_role=run.owner_role,
        runtime=run.runtime,
        adapter=run.adapter,
        autonomy_level=run.autonomy_level,
        started_at=started_at,
        eta=run.eta,
        blocker=run.blocker,
        objective=run.objective,
        current_step=run.current_step,
        related_risk=run.related_risk,
        related_assets=list(run.related_assets),
        inputs=list(run.inputs),
        proposed_outputs=list(run.proposed_outputs),
        pending_signals=[signal.model_dump() for signal in run.pending_signals],
        controls=list(run.controls),
        audit_scope=run.audit_scope,
        replay_ready=run.replay_ready,
    )
