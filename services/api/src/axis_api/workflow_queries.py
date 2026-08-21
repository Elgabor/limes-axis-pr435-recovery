from datetime import UTC

from pydantic import BaseModel, Field

from axis_api.demo import (
    ManufacturingWorkflowConsole,
    OverviewMetric,
    OverviewStatus,
    WorkflowRun,
    WorkflowTimelineEvent,
)
from axis_api.manufacturing_metadata import (
    get_manufacturing_tenant_metadata,
    operational_provenance,
)
from axis_api.models import WorkflowRunRecord, WorkflowTimelineRecord
from axis_api.persistence import AxisPersistenceRepository


class WorkflowRunQuery(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    state: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=100, ge=1, le=200)


def _isoformat_utc(value) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _timeline_event_to_public(event: WorkflowTimelineRecord) -> WorkflowTimelineEvent:
    return WorkflowTimelineEvent(
        event=event.event,
        at=_isoformat_utc(event.occurred_at),
        actor=event.actor,
        result=event.result,
        summary=event.summary,
    )


def _workflow_run_to_public(
    run: WorkflowRunRecord,
    timeline: list[WorkflowTimelineRecord],
) -> WorkflowRun:
    return WorkflowRun(
        workflow_id=run.workflow_id,
        name=run.name,
        domain=run.domain,
        state=run.state,
        status=OverviewStatus(run.status),
        owner_role=run.owner_role,
        runtime=run.runtime,
        adapter=run.adapter,
        autonomy_level=run.autonomy_level,
        started_at=_isoformat_utc(run.started_at),
        eta=run.eta,
        blocker=run.blocker,
        objective=run.objective,
        current_step=run.current_step,
        related_risk=run.related_risk,
        related_assets=run.related_assets,
        inputs=run.inputs,
        proposed_outputs=run.proposed_outputs,
        pending_signals=run.pending_signals,
        controls=run.controls,
        timeline=[_timeline_event_to_public(event) for event in timeline],
        audit_scope=run.audit_scope,
        replay_ready=run.replay_ready,
    )


def _waiting_signal_count(runs: list[WorkflowRun]) -> int:
    return sum(
        1
        for run in runs
        for signal in run.pending_signals
        if signal.status == "waiting"
    )


def _metrics(runs: list[WorkflowRun]) -> list[OverviewMetric]:
    waiting_signals = _waiting_signal_count(runs)
    return [
        OverviewMetric(
            label="Persisted Runs",
            value=str(len(runs)),
            detail="Tenant-scoped workflow runs read from Postgres",
            status=OverviewStatus.READY if runs else OverviewStatus.WATCH,
        ),
        OverviewMetric(
            label="Waiting Signals",
            value=str(waiting_signals),
            detail="Persisted workflow signals currently waiting for a decision",
            status=(
                OverviewStatus.ACTION_REQUIRED
                if waiting_signals
                else OverviewStatus.READY
            ),
        ),
        OverviewMetric(
            label="Runtime",
            value="Postgres",
            detail="Persisted workflow run state behind the Axis API",
            status=OverviewStatus.READY,
        ),
        OverviewMetric(
            label="Replay",
            value="Preview",
            detail="Replay preview artifacts are available through the simulation endpoint",
            status=OverviewStatus.WATCH,
        ),
    ]


def query_persisted_workflow_runs(
    repository: AxisPersistenceRepository,
    query: WorkflowRunQuery,
) -> ManufacturingWorkflowConsole:
    tenant_metadata = get_manufacturing_tenant_metadata(repository, query.tenant_id)
    records = repository.list_workflow_runs(
        tenant_id=query.tenant_id,
        state=query.state,
        limit=query.limit,
    )
    runs = [
        _workflow_run_to_public(
            record,
            repository.list_workflow_timeline_events(
                tenant_id=record.tenant_id,
                workflow_id=record.workflow_id,
            ),
        )
        for record in records
    ]
    has_persisted_records = bool(records)
    if not has_persisted_records and query.state is not None:
        has_persisted_records = bool(
            repository.list_workflow_runs(tenant_id=query.tenant_id, limit=1)
        )
    return ManufacturingWorkflowConsole(
        tenant_id=query.tenant_id,
        plant_name=tenant_metadata.plant_name,
        scenario=tenant_metadata.scenario,
        provenance=operational_provenance(has_persisted_records),
        as_of=runs[0].started_at if runs else tenant_metadata.as_of,
        runtime_status=OverviewStatus.READY if runs else OverviewStatus.WATCH,
        metrics=_metrics(runs),
        workflow_runs=runs,
        runtime_notes=[
            "This view is backed by persisted workflow run state.",
            "Timeline events are tenant-scoped before optional state filters.",
            "Temporal remains behind the Axis workflow runtime adapter boundary.",
            "Replay previews are available; deterministic replay and production history "
            "retention remain Platform work.",
        ],
    )
