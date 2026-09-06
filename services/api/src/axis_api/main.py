import base64
import logging
from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path as StoreRootPath
from threading import Event, Thread
from typing import Annotated, NamedTuple
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.exc import SQLAlchemyError

from axis_api.action_reference import (
    ActionReferenceRecordInvalid,
    ActionReferenceRecordNotFound,
    get_persisted_manufacturing_action_registry,
)
from axis_api.action_runs import (
    ActionPayloadValidationError,
    ActionPermissionDenied,
    ActionRunIdempotencyConflict,
    ActionRunList,
    ActionRunOutcomeConflict,
    ActionRunOutcomePermissionDenied,
    ActionRunOutcomePersistenceResult,
    ActionRunOutcomeRequest,
    ActionRunOutcomeValidationError,
    ActionRunPersistenceResult,
    ActionRunQuery,
    ActionRunRequest,
    DemoActionNotFound,
    DemoActionRunNotFound,
    list_action_run_records,
    record_demo_action_run,
    record_demo_action_run_outcome,
)
from axis_api.agent_reference import (
    AgentReferenceRecordInvalid,
    AgentReferenceRecordNotFound,
    get_persisted_manufacturing_agent_registry,
)
from axis_api.agent_runs import (
    AgentRunAgentNotExecutable,
    AgentRunAgentNotFound,
    AgentRunCursorError,
    AgentRunIdempotencyConflict,
    AgentRunList,
    AgentRunNotFound,
    AgentRunPermissionDenied,
    AgentRunResult,
    AgentRunStartRequest,
    decode_agent_run_cursor,
    encode_agent_run_cursor,
    get_agent_run_result,
    list_agent_run_results,
    start_agent_run,
)
from axis_api.approval_decisions import (
    ApprovalDecisionConflict,
    ApprovalDecisionPersistenceResult,
    ApprovalDecisionRequest,
    ApprovalPermissionDenied,
    DemoApprovalNotFound,
    record_demo_approval_decision,
)
from axis_api.approval_outbox import (
    ApprovalDecisionDeliveryStatus,
    get_approval_decision_delivery_status,
)
from axis_api.approval_reference import (
    ApprovalReferenceRecordInvalid,
    ApprovalReferenceRecordNotFound,
    get_persisted_manufacturing_approval_inbox,
)
from axis_api.audit import AuditEventCreate
from axis_api.audit_queries import (
    LEGAL_HOLD_REQUIRED_SCOPE,
    RETENTION_DELETION_REQUIRED_SCOPE,
    AuditEventQuery,
    AuditExportBundle,
    AuditExportQuery,
    AuditExportWormEnforcementError,
    AuditLegalHoldConflict,
    AuditLegalHoldCreateRequest,
    AuditLegalHoldNotFound,
    AuditLegalHoldPermissionDenied,
    AuditLegalHoldRecord,
    AuditLegalHoldReleaseRequest,
    AuditObjectLegalHoldRecord,
    AuditObjectLegalHoldRequest,
    AuditRetentionDeletionPermissionDenied,
    AuditRetentionDeletionRequest,
    AuditRetentionDeletionResult,
    apply_object_legal_hold,
    create_audit_legal_hold,
    execute_audit_retention_deletion,
    export_persisted_audit_events,
    list_audit_legal_holds,
    query_persisted_audit_events,
    release_audit_legal_hold,
    release_object_legal_hold,
)
from axis_api.audit_reference import (
    AuditReferenceRecordInvalid,
    AuditReferenceRecordNotFound,
    get_persisted_manufacturing_audit_explorer,
)
from axis_api.audit_signing import SelfHostedAuditLedgerSigner
from axis_api.config import Settings, validate_runtime_configuration
from axis_api.connector_configurations import (
    ConnectorConfigurationCreateRequest,
    ConnectorConfigurationQuery,
    ConnectorConfigurationValidationError,
    ConnectorTenantConfiguration,
    ManufacturingConnectorConfigurationRegistry,
    build_connector_configuration_registry,
    record_demo_connector_configuration,
)
from axis_api.connector_credential_handles import (
    ConnectorCredentialHandleCreateRequest,
    ConnectorCredentialHandleQuery,
    ConnectorCredentialHandleRecord,
    ConnectorCredentialHandleValidationError,
    ConnectorCredentialRotationRequest,
    ManufacturingConnectorCredentialHandleRegistry,
    build_connector_credential_handle_registry,
    record_demo_connector_credential_handle,
    record_demo_connector_credential_rotation,
)
from axis_api.connector_credential_leases import (
    ConnectorCredentialLeaseConflict,
    ConnectorCredentialLeasePermissionDenied,
    ConnectorCredentialLeaseQuery,
    ConnectorCredentialLeaseRecord,
    ConnectorCredentialLeaseRenewRequest,
    ConnectorCredentialLeaseRequest,
    ConnectorCredentialLeaseRevokeRequest,
    ConnectorCredentialLeaseValidationError,
    CredentialLeaseRuntime,
    DeferredCredentialLeaseRuntime,
    ManufacturingConnectorCredentialLeaseRegistry,
    ProviderSpecificVaultKmsLeaseRuntime,
    SelfHostedVaultKmsLeaseRuntime,
    read_connector_credential_lease_registry,
    record_demo_connector_credential_lease,
    renew_demo_connector_credential_lease,
    revoke_demo_connector_credential_lease,
)
from axis_api.connector_egress_policies import (
    ConnectorEgressPolicyCreateRequest,
    ConnectorEgressPolicyQuery,
    ConnectorEgressPolicyRecord,
    ConnectorEgressPolicyValidationError,
    ManufacturingConnectorEgressPolicyRegistry,
    read_connector_egress_policy_registry,
    record_demo_connector_egress_policy,
)
from axis_api.connector_evidence_invariants import (
    ConnectorEvidenceInvariantQuery,
    ConnectorEvidenceInvariantSnapshotConflict,
    ConnectorEvidenceInvariantSnapshotExportBundle,
    ConnectorEvidenceInvariantSnapshotExportDecisionPermissionDenied,
    ConnectorEvidenceInvariantSnapshotExportDecisionRequest,
    ConnectorEvidenceInvariantSnapshotExportDecisionResult,
    ConnectorEvidenceInvariantSnapshotExportMaterializationConflict,
    ConnectorEvidenceInvariantSnapshotExportMaterializationPermissionDenied,
    ConnectorEvidenceInvariantSnapshotExportMaterializationRequest,
    ConnectorEvidenceInvariantSnapshotExportMaterializationResult,
    ConnectorEvidenceInvariantSnapshotExportQuery,
    ConnectorEvidenceInvariantSnapshotExportRequest,
    ConnectorEvidenceInvariantSnapshotExportRequestConflict,
    ConnectorEvidenceInvariantSnapshotExportRequestNotFound,
    ConnectorEvidenceInvariantSnapshotExportRequestRecord,
    ConnectorEvidenceInvariantSnapshotHistory,
    ConnectorEvidenceInvariantSnapshotPermissionDenied,
    ConnectorEvidenceInvariantSnapshotQuery,
    ConnectorEvidenceInvariantSnapshotRecord,
    ConnectorEvidenceInvariantSnapshotRequest,
    ManufacturingConnectorEvidenceInvariantReport,
    export_connector_evidence_invariant_snapshots,
    materialize_connector_evidence_invariant_snapshot_export_request,
    persist_connector_evidence_invariant_snapshot,
    read_connector_evidence_invariant_report,
    read_connector_evidence_invariant_snapshot_history,
    record_connector_evidence_invariant_snapshot_export_request,
    record_connector_evidence_invariant_snapshot_export_request_decision,
)
from axis_api.connector_execution import (
    ConnectorExecutionRuntime,
    ConnectorLiveSyncRuntime,
    ConnectorSyncDispatchRuntime,
    ConnectorSyncExecutionRuntime,
    ConnectorSyncSchedulerRuntime,
    DeferredConnectorExecutionRuntime,
    DeferredConnectorSyncDispatchRuntime,
    DeferredConnectorSyncSchedulerRuntime,
    connector_live_sync_runtime_from_settings,
    connector_sync_execution_runtime_from_settings,
)
from axis_api.connector_manifests import (
    MANIFEST_VALIDATION_BATCH_LIMIT,
    ConnectorManifestBatchValidationRequest,
    ConnectorManifestBatchValidationResponse,
    ConnectorManifestConflict,
    ConnectorManifestCreateRequest,
    ConnectorManifestDetail,
    ConnectorManifestLifecycleRequest,
    ConnectorManifestLifecycleValidationError,
    ConnectorManifestNotFound,
    ConnectorManifestQuery,
    ConnectorManifestRecordView,
    ConnectorManifestReplaceRequest,
    ConnectorManifestRevisionConflict,
    ConnectorManifestValidationError,
    ManufacturingConnectorManifestRegistry,
    build_connector_manifest_registry,
    get_connector_manifest_detail,
    overlay_registered_connector_manifest,
    record_demo_connector_manifest,
    replace_demo_connector_manifest,
    transition_demo_connector_manifest_lifecycle,
    validate_connector_manifest_batch,
)
from axis_api.connector_manual_imports import (
    ConnectorManualImportCreateRequest,
    ConnectorManualImportDecisionRequest,
    ConnectorManualImportDecisionResult,
    ConnectorManualImportIdempotencyConflict,
    ConnectorManualImportNotFound,
    ConnectorManualImportPermissionDenied,
    ConnectorManualImportQuery,
    ConnectorManualImportRecord,
    ConnectorManualImportValidationError,
    ManufacturingConnectorManualImportRegistry,
    build_connector_manual_import_registry,
    record_demo_connector_manual_import,
    record_demo_connector_manual_import_decision,
)
from axis_api.connector_ontology_promotions import (
    ConnectorOntologyPromotionIdempotencyConflict,
    ConnectorOntologyPromotionNotFound,
    ConnectorOntologyPromotionPermissionDenied,
    ConnectorOntologyPromotionRequest,
    ConnectorOntologyPromotionResult,
    ConnectorOntologyPromotionValidationError,
    record_demo_connector_ontology_promotion,
)
from axis_api.connector_ontology_proposals import (
    ConnectorOntologyProposalCreateRequest,
    ConnectorOntologyProposalQuery,
    ConnectorOntologyProposalValidationError,
    ManufacturingConnectorOntologyProposalRegistry,
    build_connector_ontology_proposal_registry,
    record_demo_connector_ontology_proposals,
)
from axis_api.connector_postgres_discovery import (
    ConnectorSourceDiscoveryRequest,
    ConnectorSourceDiscoveryRuntime,
    ConnectorSourceOperationError,
    ConnectorSourceVerifyRequest,
    SourceDiscoveryOutcome,
    SourceScopeDenied,
    SourceVerificationOutcome,
    connector_source_discovery_runtime_from_settings,
    record_connector_source_discovery,
    record_connector_source_verification,
)
from axis_api.connector_promotion_policies import (
    ConnectorPromotionPolicyConflict,
    ConnectorPromotionPolicyCreateRequest,
    ConnectorPromotionPolicyEnableRequest,
    ConnectorPromotionPolicyNotFound,
    ConnectorPromotionPolicyPermissionDenied,
    ConnectorPromotionPolicyQuery,
    ConnectorPromotionPolicyRecord,
    ConnectorPromotionPolicyReviseRequest,
    ConnectorPromotionPolicyValidationError,
    ManufacturingConnectorPromotionPolicyRegistry,
    build_connector_promotion_policy_registry,
    enable_demo_connector_promotion_policy,
    record_demo_connector_promotion_policy,
    revise_demo_connector_promotion_policy,
)
from axis_api.connector_promotion_policy_sets import (
    ConnectorPromotionPolicySetActivateRequest,
    ConnectorPromotionPolicySetConflict,
    ConnectorPromotionPolicySetPermissionDenied,
    ConnectorPromotionPolicySetQuery,
    ConnectorPromotionPolicySetRecord,
    ConnectorPromotionPolicySetValidationError,
    ManufacturingConnectorPromotionPolicySetRegistry,
    build_connector_promotion_policy_set_registry,
    record_demo_connector_promotion_policy_set,
)
from axis_api.connector_reference import (
    ConnectorReferenceRecordInvalid,
    ConnectorReferenceRecordNotFound,
    get_persisted_manufacturing_connector_registry,
    require_persisted_manufacturing_connector_registry,
)
from axis_api.connector_runs import (
    SYNC_CHECKPOINT_CLAIM_READ_SCOPE,
    SYNC_CHECKPOINT_READ_SCOPE,
    ConnectorRunCreateRequest,
    ConnectorRunDispatchConflict,
    ConnectorRunDispatchRequest,
    ConnectorRunNotFound,
    ConnectorRunPermissionDenied,
    ConnectorRunQuery,
    ConnectorRunRecord,
    ConnectorRunSyncExecutionConflict,
    ConnectorRunSyncExecutionRequest,
    ConnectorRunValidationError,
    ConnectorSyncCheckpointClaimConflict,
    ConnectorSyncCheckpointClaimQuery,
    ConnectorSyncCheckpointClaimRecord,
    ConnectorSyncCheckpointClaimReleaseRequest,
    ConnectorSyncCheckpointClaimRenewRequest,
    ConnectorSyncCheckpointClaimRequest,
    ConnectorSyncCheckpointQuery,
    ManufacturingConnectorRunRegistry,
    ManufacturingConnectorSyncCheckpointClaimRegistry,
    ManufacturingConnectorSyncCheckpointRegistry,
    build_connector_run_registry,
    claim_connector_sync_checkpoint,
    dispatch_demo_connector_sync,
    execute_demo_connector_sync,
    read_connector_sync_checkpoint_claim_registry,
    read_connector_sync_checkpoint_registry,
    record_demo_connector_run,
    release_connector_sync_checkpoint_claim,
    renew_connector_sync_checkpoint_claim,
)
from axis_api.connector_source_activation import (
    ConnectorSourceActivationConflict,
    ConnectorSourceActivationError,
    ConnectorSourceActivationOutcome,
    ConnectorSourceActivationRequest,
    ConnectorSourceBindingsView,
    SourceActivationScopeDenied,
    list_connector_source_bindings,
    record_connector_source_activation,
)
from axis_api.connector_source_batch_exports import (
    ConnectorSourceBatchExportDecisionInput,
    ConnectorSourceBatchExportDecisionResult,
    ConnectorSourceBatchExportError,
    ConnectorSourceBatchExportMaterializationInput,
    ConnectorSourceBatchExportMaterializationResult,
    ConnectorSourceBatchExportRequestInput,
    ConnectorSourceBatchExportRequestRecord,
    ConnectorSourceBatchExportScopeDenied,
    LocalBatchExportArtifactReader,
    decide_connector_source_batch_export_request,
    materialize_connector_source_batch_export_request,
    read_connector_source_batch_export_artifact,
    record_connector_source_batch_export_request,
)
from axis_api.connector_source_extraction import planned_extraction_limits
from axis_api.connector_source_extraction_reconciliation import (
    LocalReconcilableObjectStore,
    SourceExtractionReconciliationReport,
    reconcile_request_batches,
)
from axis_api.connector_source_ingestion import (
    SOURCE_INGESTION_READ_SCOPE,
    ConnectorSourceIngestionCancelRequest,
    ConnectorSourceIngestionError,
    ConnectorSourceIngestionOverview,
    ConnectorSourceIngestionRequeueRequest,
    ConnectorSourceIngestionSubmission,
    SourceExtractionBatchesPage,
    SourceIngestionEligibilityView,
    SourceIngestionRequestView,
    SourceIngestionScopeDenied,
    build_connector_source_ingestion_overview,
    cancel_connector_source_ingestion_request,
    get_connector_source_ingestion_request_view,
    list_connector_source_extraction_batches_page,
    list_connector_source_ingestion_request_views,
    max_source_ingestion_selections,
    preview_source_ingestion_eligibility,
    record_connector_source_ingestion_request,
    requeue_connector_source_ingestion_request,
)
from axis_api.connectors import (
    ConnectorCsvPreviewRequest,
    ConnectorCsvPreviewResult,
    ConnectorExternalDbPreviewRequest,
    ConnectorExternalDbPreviewResult,
    ManufacturingConnectorRegistry,
    preview_external_db_connector,
    preview_file_csv_connector,
)
from axis_api.csrf import BrowserSessionCsrfMiddleware
from axis_api.data_asset_contracts import (
    DataAssetContractConflict,
    DataAssetContractDeclarationRequest,
    DataAssetContractEvaluationView,
    DataAssetContractView,
    declare_data_asset_contract,
    evaluate_data_asset_contract,
    get_data_asset_contract_view,
)
from axis_api.data_asset_discovery import (
    DataAssetResourcesView,
    list_data_asset_resources,
    record_data_resource_observation,
)
from axis_api.data_asset_lineage import (
    DataAssetLineageView,
    build_data_asset_lineage_view,
)
from axis_api.data_asset_stewardship import (
    DataAssetStewardshipConflict,
    DataAssetStewardshipDeclarationRequest,
    DataAssetStewardshipView,
    declare_data_asset_stewardship,
    get_data_asset_stewardship_view,
    stewardship_summary_for_asset,
)
from axis_api.data_assets import (
    DataAssetCatalog,
    DataAssetNotInCatalog,
    build_data_asset_catalog,
    ensure_data_asset_in_catalog,
)
from axis_api.db import create_session_factory, session_scope
from axis_api.demo import (
    ManufacturingActionRegistry,
    ManufacturingAgentRegistry,
    ManufacturingApprovalInbox,
    ManufacturingAuditExplorer,
    ManufacturingModelRouting,
    ManufacturingOntology,
    ManufacturingOntologyEntityDetail,
    ManufacturingOverview,
    ManufacturingWorkflowConsole,
)
from axis_api.demo_bootstrap import (
    DemoBootstrapPermissionDenied,
    DemoBootstrapRecordView,
    DemoBootstrapRequest,
    DemoBootstrapValidationError,
    bootstrap_demo_scenario,
)
from axis_api.demo_reference import (
    DemoReferenceRecordInvalid,
    DemoReferenceRecordNotFound,
    get_persisted_manufacturing_overview,
)
from axis_api.deployment_readiness import (
    DeploymentReadinessReport,
    build_deployment_readiness_report,
)
from axis_api.errors import AxisErrorCode
from axis_api.identity import (
    ACTOR_MISMATCH_MESSAGE,
    TENANT_MISMATCH_MESSAGE,
    ActorBindingError,
    OidcAuthenticationError,
    OidcPrincipal,
    RemoteJwksOidcVerifier,
    bind_request_actor,
    resolve_declared_actor,
)
from axis_api.identity_session import (
    IdentityBrowserSessionList,
    IdentityBrowserSessionRecord,
    IdentitySessionCursorError,
    IdentitySessionReadModel,
    build_identity_session_read_model,
    decode_session_cursor,
    encode_session_cursor,
)
from axis_api.manufacturing_metadata import ManufacturingTenantNotFound
from axis_api.manufacturing_operations import (
    DailyPlantBriefIdempotencyConflict,
    DailyPlantBriefPermissionDenied,
    DailyPlantBriefRecord,
    DailyPlantBriefRequest,
    DailyPlantBriefValidationError,
    MaintenanceRiskScenarioIdempotencyConflict,
    MaintenanceRiskScenarioPermissionDenied,
    MaintenanceRiskScenarioRecord,
    MaintenanceRiskScenarioRequest,
    MaintenanceRiskScenarioValidationError,
    ManufacturingDemoReadinessReport,
    ManufacturingNotificationAcknowledgementConflict,
    ManufacturingNotificationAcknowledgementPermissionDenied,
    ManufacturingNotificationAcknowledgementRequest,
    ManufacturingNotificationAcknowledgementResult,
    ManufacturingNotificationCenter,
    ManufacturingNotificationNotFound,
    ManufacturingNotificationQuery,
    ManufacturingOperationQuery,
    ManufacturingOperationsDataset,
    ManufacturingOperationsSnapshot,
    ManufacturingOperationsSnapshotQuery,
    QualityRiskScenarioIdempotencyConflict,
    QualityRiskScenarioPermissionDenied,
    QualityRiskScenarioRecord,
    QualityRiskScenarioRequest,
    QualityRiskScenarioValidationError,
    SupplierDelayScenarioIdempotencyConflict,
    SupplierDelayScenarioPermissionDenied,
    SupplierDelayScenarioRecord,
    SupplierDelayScenarioRequest,
    SupplierDelayScenarioValidationError,
    build_manufacturing_demo_readiness_report,
    build_manufacturing_notification_center,
    build_manufacturing_operations_snapshot,
    generate_daily_plant_brief,
    generate_maintenance_risk_scenario,
    generate_quality_risk_scenario,
    generate_supplier_delay_scenario,
    query_manufacturing_operations_dataset,
    record_manufacturing_notification_acknowledgement,
)
from axis_api.model_endpoints import (
    MODEL_ENDPOINT_READ_SCOPE,
    ModelEndpointConflict,
    ModelEndpointCreateRequest,
    ModelEndpointNotFound,
    ModelEndpointPermissionDenied,
    ModelEndpointRecord,
    ModelEndpointRegistry,
    ModelEndpointStatusUpdateRequest,
    ModelEndpointValidationError,
    build_model_endpoint_registry,
    record_model_endpoint,
    update_model_endpoint_status,
)
from axis_api.model_invocations import (
    ModelEgressBlocked,
    ModelInvocationCursorError,
    ModelInvocationIdempotencyConflict,
    ModelInvocationList,
    ModelInvocationNotFound,
    ModelInvocationPermissionDenied,
    ModelInvocationPreview,
    ModelInvocationPreviewRequest,
    ModelInvocationRequest,
    ModelInvocationResult,
    ModelInvocationValidationError,
    ModelRoutingTelemetryProjection,
    build_model_routing_telemetry,
    decode_model_invocation_cursor,
    encode_model_invocation_cursor,
    get_model_invocation_result,
    invoke_model,
    list_model_invocation_results,
    preview_model_invocation,
)
from axis_api.model_providers import (
    DeferredModelInvocationRuntime,
    ModelInvocationRuntime,
    SelfHostedOpenAICompatibleRuntime,
)
from axis_api.model_routing_reference import (
    ModelRoutingReferenceRecordInvalid,
    get_persisted_manufacturing_model_routing,
)
from axis_api.models import OidcBrowserSession
from axis_api.object_storage import (
    COMPLIANCE_RETENTION_MODE,
    LOCAL_FILESYSTEM_ADAPTER,
    LocalObjectStore,
    ObjectLockCapability,
    ObjectStore,
    ObjectStoreConfigurationError,
    build_connector_export_object_store,
    probe_object_lock_capability,
)
from axis_api.oidc_code_flow import (
    OidcCodeFlowConfigurationError,
    OidcCookieValidationError,
    OidcTokenExchangeError,
    authorization_endpoint,
    build_authorization_request,
    build_end_session_redirect_url,
    build_refresh_token_form,
    build_token_exchange_form,
    csrf_cookie_name,
    csrf_token_for_session,
    decrypt_refresh_token,
    encrypt_refresh_token,
    end_session_endpoint,
    exchange_authorization_code,
    post_logout_redirect_uri,
    public_redirect,
    read_login_state,
    read_session_cookie,
    refresh_token_encryption_key_is_strong,
    session_cookie_from_principal,
    session_cookie_name,
    session_id_hash,
    token_endpoint,
    validate_refresh_token_encryption_key,
)
from axis_api.oidc_onboarding import OidcOnboardingReport, build_oidc_onboarding_report
from axis_api.ontology.mutations import (
    DeferredOntologyMutationRuntime,
    OntologyMutationRuntime,
    TypeDBOntologyMutationConfig,
    TypeDBOntologyMutationRuntime,
)
from axis_api.ontology.queries import (
    DeferredOntologyQueryRuntime,
    OntologyGraphQueryRequest,
    OntologyGraphQueryRuntime,
    TypeDBOntologyQueryConfig,
    TypeDBOntologyQueryRuntime,
    query_manufacturing_ontology_graph,
)
from axis_api.ontology_authorization import (
    OntologyReadPermissionDenied,
    authorize_ontology_graph_read,
    get_authorized_manufacturing_ontology_entity_detail,
)
from axis_api.ontology_reference import (
    OntologyReferenceRecordInvalid,
    OntologyReferenceRecordNotFound,
    get_persisted_manufacturing_ontology,
)
from axis_api.permissions import (
    TENANT_MISMATCH_REASON,
    ScopeAuthorizationError,
    authorize_principal_scopes,
)
from axis_api.persistence import (
    AxisPersistenceRepository,
    OidcBrowserSessionCreate,
    OidcBrowserSessionRevocation,
)
from axis_api.platform_policies import (
    REQUIRED_READ_SCOPE as PLATFORM_POLICY_READ_SCOPE,
)
from axis_api.platform_policies import (
    PlatformPolicyConflict,
    PlatformPolicyCreateRequest,
    PlatformPolicyDecision,
    PlatformPolicyDetail,
    PlatformPolicyEnforcementDenied,
    PlatformPolicyEvaluationRequest,
    PlatformPolicyNotFound,
    PlatformPolicyPermissionDenied,
    PlatformPolicyQuery,
    PlatformPolicyRecord,
    PlatformPolicyRegistry,
    PlatformPolicyReviseRequest,
    PlatformPolicyRevisionConflict,
    PlatformPolicyScope,
    PlatformPolicyValidationError,
    build_platform_policy_registry,
    evaluate_platform_policy_request,
    get_platform_policy_detail,
    record_platform_policy,
    revise_platform_policy,
)
from axis_api.platform_tenants import (
    REQUIRED_OPERATOR_SCOPE as PLATFORM_TENANT_OPERATOR_SCOPE,
)
from axis_api.platform_tenants import (
    REQUIRED_READ_SCOPE as PLATFORM_TENANT_READ_SCOPE,
)
from axis_api.platform_tenants import (
    TenantLifecycleConflict,
    TenantLifecycleStatus,
    TenantListCursorError,
    TenantNotFound,
    TenantPermissionDenied,
    TenantProvisionConflict,
    TenantProvisionRequest,
    TenantQuotaKey,
    TenantQuotaSet,
    TenantQuotaUpdateRequest,
    TenantReactivateRequest,
    TenantRecord,
    TenantRegistry,
    TenantStateCache,
    TenantSuspendRequest,
    TenantVocabularySet,
    TenantVocabularyUpdateRequest,
    build_tenant_registry,
    decode_tenant_cursor,
    get_tenant_detail,
    get_tenant_quota_set,
    get_tenant_vocabulary,
    provision_tenant,
    reactivate_tenant,
    suspend_tenant,
    update_tenant_quotas,
    update_tenant_vocabulary,
)
from axis_api.rate_limit import (
    ApiRateLimitMiddleware,
    RateLimitBackend,
    build_rate_limit_backend,
)
from axis_api.replay_simulation import (
    ManufacturingReplaySimulation,
    ReplayPolicySetDiffDisabled,
    ReplayPolicySetDiffValidationError,
    ReplaySimulationOutputConflict,
    ReplaySimulationOutputPermissionDenied,
    ReplaySimulationOutputPersistRequest,
    ReplaySimulationOutputRecord,
    ReplaySimulationOutputValidationError,
    ReplaySimulationQuery,
    build_replay_simulation,
    persist_replay_simulation_output,
)
from axis_api.request_correlation import (
    REQUEST_ID_HEADER,
    RequestCorrelationMiddleware,
    new_request_id,
)
from axis_api.runtime_readiness import (
    RuntimeReadinessService,
    build_runtime_readiness_service,
)
from axis_api.session_lifecycle import (
    browser_session_lifecycle_failure,
    ensure_aware_datetime,
)
from axis_api.session_metadata import extract_session_client_metadata
from axis_api.support_diagnostics import (
    SupportDiagnosticsReport,
    build_support_diagnostics_report,
)
from axis_api.system_routes import build_system_router
from axis_api.telemetry import (
    ATTR_ACTION_ID,
    ATTR_ACTOR_ID,
    ATTR_APPROVAL_ID,
    ATTR_CONNECTOR_ID,
    ATTR_DECISION,
    ATTR_EXPORT_FORMAT,
    ATTR_MODEL_ID,
    ATTR_MODEL_INPUT_TOKENS,
    ATTR_MODEL_LATENCY_MS,
    ATTR_MODEL_OUTPUT_TOKENS,
    ATTR_MODEL_PROVIDER_ID,
    ATTR_OUTCOME,
    ATTR_TENANT_ID,
    TelemetryRuntime,
    annotate_current_span,
    configure_api_telemetry,
    instrument_fastapi_app,
    set_span_attributes,
    shutdown_providers,
)
from axis_api.tenant_admission import (
    tenant_admission_denial_audit_event_type,
    tenant_admission_denial_reason,
)
from axis_api.usage_metering import (
    REQUIRED_USAGE_READ_SCOPE as PLATFORM_TENANT_USAGE_SCOPE,
)
from axis_api.usage_metering import (
    RequestUsageAdmissionRecorder,
    TenantUsageMetric,
    TenantUsageSummary,
    UsageEventProjector,
    build_tenant_usage_summary,
    record_tenant_usage_event,
)
from axis_api.workflow_queries import WorkflowRunQuery, query_persisted_workflow_runs
from axis_api.workflow_reference import (
    WorkflowReferenceRecordInvalid,
    WorkflowReferenceRecordNotFound,
    get_persisted_manufacturing_workflow_console,
)
from axis_api.workflow_runtime import (
    DeferredWorkflowSignalRuntime,
    TemporalWorkflowSignalConfig,
    TemporalWorkflowSignalRuntime,
    WorkflowSignalRuntime,
)

_LOGGER = logging.getLogger("axis_api")


def persistence_repository(request: Request) -> Generator[AxisPersistenceRepository]:
    with session_scope(request.app.state.session_factory) as session:
        repository = AxisPersistenceRepository(session)
        yield repository
    repository.run_after_commit_callbacks()


PersistenceRepository = Annotated[
    AxisPersistenceRepository,
    Depends(persistence_repository),
]


def workflow_runtime(request: Request) -> WorkflowSignalRuntime:
    return request.app.state.workflow_runtime


WorkflowRuntime = Annotated[
    WorkflowSignalRuntime,
    Depends(workflow_runtime),
]


def connector_export_object_store(request: Request) -> ObjectStore:
    try:
        return build_connector_export_object_store(request.app.state.settings)
    except ObjectStoreConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": AxisErrorCode.CONNECTOR_UNAVAILABLE.value,
                "message": "Connector evidence object storage is not configured.",
                "reason": "object_store_misconfigured",
            },
        ) from exc


ConnectorExportObjectStore = Annotated[
    ObjectStore,
    Depends(connector_export_object_store),
]


def _audit_export_object_lock_capability(app: FastAPI) -> ObjectLockCapability:
    """Probe the audit-export bucket object-lock capability, caching positives.

    Only an enforceable (positive) result is cached: S3 object-lock cannot be
    disabled once a bucket is created with it, so a verified capability is
    stable for the process lifetime. A negative or error result (transient
    bucket outage, probe failure) is NOT cached, so the gate re-probes on the
    next call and a recovered bucket restores COMPLIANCE without an API restart.

    Tests may pin a fixed capability (positive or negative) via
    ``app.state.audit_export_object_lock_capability_override``; that override is
    always authoritative and is never re-probed.
    """

    override = getattr(app.state, "audit_export_object_lock_capability_override", None)
    if isinstance(override, ObjectLockCapability):
        return override
    cached = getattr(app.state, "audit_export_object_lock_capability", None)
    if isinstance(cached, ObjectLockCapability) and cached.compliance_enforceable:
        return cached
    capability = probe_object_lock_capability(app.state.settings)
    if capability.compliance_enforceable:
        app.state.audit_export_object_lock_capability = capability
    return capability


def _audit_export_worm_settings(settings: Settings) -> bool:
    return settings.connector_export_s3_retention_mode.strip().upper() == (
        COMPLIANCE_RETENTION_MODE
    )


def _warm_audit_export_object_lock_capability(app: FastAPI) -> None:
    """Non-fatal startup cache-warm + log of the object-lock capability.

    When COMPLIANCE retention is configured this probes the bucket once at
    startup so readiness reflects the capability immediately and operators get
    a boot-time signal. It never fails boot: a non-enforceable result is logged
    (not cached, per the re-probe policy) and the export gate still fails closed
    per request until the bucket is verified.
    """

    if not _audit_export_worm_settings(app.state.settings):
        return
    try:
        capability = _audit_export_object_lock_capability(app)
    except Exception:  # noqa: BLE001 - startup warm-up must never fail boot
        _LOGGER.warning(
            "Audit-export object-lock capability probe failed at startup; "
            "COMPLIANCE exports will fail closed until the bucket is verified.",
            exc_info=True,
        )
        return
    if capability.compliance_enforceable:
        _LOGGER.info(
            "Audit-export object-lock capability verified at startup: %s",
            capability.reason,
        )
    else:
        _LOGGER.warning(
            "Audit-export object-lock capability NOT enforceable at startup "
            "(COMPLIANCE exports will fail closed until verified): %s",
            capability.reason,
        )


def ontology_mutation_runtime(request: Request) -> OntologyMutationRuntime:
    return request.app.state.ontology_mutation_runtime


OntologyMutationRuntimeDependency = Annotated[
    OntologyMutationRuntime,
    Depends(ontology_mutation_runtime),
]


def ontology_query_runtime(request: Request) -> OntologyGraphQueryRuntime:
    return request.app.state.ontology_query_runtime


OntologyQueryRuntimeDependency = Annotated[
    OntologyGraphQueryRuntime,
    Depends(ontology_query_runtime),
]


def connector_execution_runtime(request: Request) -> ConnectorExecutionRuntime:
    return request.app.state.connector_execution_runtime


ConnectorExecutionRuntimeDependency = Annotated[
    ConnectorExecutionRuntime,
    Depends(connector_execution_runtime),
]


def connector_sync_scheduler_runtime(request: Request) -> ConnectorSyncSchedulerRuntime:
    return request.app.state.connector_sync_scheduler_runtime


ConnectorSyncSchedulerRuntimeDependency = Annotated[
    ConnectorSyncSchedulerRuntime,
    Depends(connector_sync_scheduler_runtime),
]


def connector_sync_dispatch_runtime(request: Request) -> ConnectorSyncDispatchRuntime:
    return request.app.state.connector_sync_dispatch_runtime


ConnectorSyncDispatchRuntimeDependency = Annotated[
    ConnectorSyncDispatchRuntime,
    Depends(connector_sync_dispatch_runtime),
]


def connector_sync_execution_runtime(request: Request) -> ConnectorSyncExecutionRuntime:
    return request.app.state.connector_sync_execution_runtime


ConnectorSyncExecutionRuntimeDependency = Annotated[
    ConnectorSyncExecutionRuntime,
    Depends(connector_sync_execution_runtime),
]


def connector_live_sync_runtime(request: Request) -> ConnectorLiveSyncRuntime:
    return request.app.state.connector_live_sync_runtime


ConnectorLiveSyncRuntimeDependency = Annotated[
    ConnectorLiveSyncRuntime,
    Depends(connector_live_sync_runtime),
]


def connector_source_discovery_runtime(
    request: Request,
) -> ConnectorSourceDiscoveryRuntime:
    return request.app.state.connector_source_discovery_runtime


ConnectorSourceDiscoveryRuntimeDependency = Annotated[
    ConnectorSourceDiscoveryRuntime,
    Depends(connector_source_discovery_runtime),
]


def credential_lease_runtime(request: Request) -> CredentialLeaseRuntime:
    return request.app.state.credential_lease_runtime


CredentialLeaseRuntimeDependency = Annotated[
    CredentialLeaseRuntime,
    Depends(credential_lease_runtime),
]


def model_invocation_runtime(request: Request) -> ModelInvocationRuntime:
    return request.app.state.model_invocation_runtime


ModelInvocationRuntimeDependency = Annotated[
    ModelInvocationRuntime,
    Depends(model_invocation_runtime),
]


def _record_request_usage_admission(
    request: Request,
    principal: OidcPrincipal,
) -> None:
    recorder: RequestUsageAdmissionRecorder | None = getattr(
        request.app.state,
        "request_usage_admission_recorder",
        None,
    )
    if recorder is None:
        return
    try:
        recorder.record(request, principal)
    except Exception as exc:  # noqa: BLE001 - policy decides fail-open/closed
        _LOGGER.error(
            "Request usage admission persistence failed.",
            extra={"metric": TenantUsageMetric.API_REQUEST.value},
            exc_info=True,
        )
        settings: Settings = request.app.state.settings
        if settings.usage_metering_failure_mode == "closed":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": AxisErrorCode.CONTROL_PLANE_UNAVAILABLE.value,
                    "message": "Request usage admission is temporarily unavailable.",
                    "reason": "usage_metering_unavailable",
                },
            ) from exc


def _resolve_request_principal(
    request: Request,
    authorization: str | None,
) -> tuple[OidcPrincipal | None, str | None]:
    """Resolve the verified request principal without raising auth failures.

    Returns ``(principal, None)`` on success, or ``(None, reason)`` with
    ``reason`` drawn from the same public classification the 401 responses
    already expose (``missing_authorization``, ``invalid_session_cookie``,
    ``expired_session_cookie``, ``invalid_token``, ...). Tenant admission for
    every successfully verified principal — bearer, cookie, or previously
    cached — fails closed here, so no caller can skip it.
    """
    settings: Settings = request.app.state.settings
    cached_principal = getattr(request.state, "axis_principal", None)
    if authorization and isinstance(cached_principal, OidcPrincipal):
        _enforce_tenant_admission(request, cached_principal)
        return cached_principal, None
    if not authorization:
        session_cookie = request.cookies.get(session_cookie_name(settings))
        if session_cookie:
            try:
                oidc_session = read_session_cookie(session_cookie, settings)
                session_hash = session_id_hash(oidc_session.session_id, settings)
                cookie_failure_reason: str | None = None
                principal: OidcPrincipal | None = None
                with session_scope(request.app.state.session_factory) as session:
                    repository = AxisPersistenceRepository(session)
                    stored_session = repository.get_oidc_browser_session_by_hash(session_hash)
                    if stored_session is None:
                        cookie_failure_reason = "invalid_session_cookie"
                    else:
                        failure = browser_session_lifecycle_failure(stored_session, settings)
                        if failure is not None:
                            public_reason, revocation_reason = failure
                            if revocation_reason and stored_session.status in {
                                "active",
                                "refreshing",
                            }:
                                _expire_stored_session(
                                    repository,
                                    stored_session,
                                    revocation_reason=revocation_reason,
                                )
                            cookie_failure_reason = public_reason
                        elif (
                            stored_session.actor_id != oidc_session.actor_id
                            or stored_session.tenant_id != oidc_session.tenant_id
                        ):
                            cookie_failure_reason = "invalid_session_cookie"
                        else:
                            repository.touch_oidc_browser_session(session_hash, datetime.now(UTC))
                            principal = OidcPrincipal(
                                actor_id=stored_session.actor_id,
                                tenant_id=stored_session.tenant_id,
                                scopes=list(stored_session.scopes),
                                expires_at=int(
                                    ensure_aware_datetime(stored_session.expires_at).timestamp()
                                ),
                                session_source="secure_cookie",
                            )
                if cookie_failure_reason is not None:
                    return None, cookie_failure_reason
                if principal is not None:
                    _enforce_tenant_admission(request, principal)
                    request.state.axis_principal = principal
                    return principal, None
            except (
                OidcCodeFlowConfigurationError,
                OidcCookieValidationError,
            ) as exc:
                # Configuration problems are deliberately not distinguishable
                # from tampered cookies here: the public reason taxonomy stays
                # within the four browser-session failure classes.
                reason = getattr(exc, "reason", "invalid_session_cookie")
                public_reason = (
                    reason
                    if reason
                    in {
                        "invalid_session_cookie",
                        "revoked_session_cookie",
                        "expired_session_cookie",
                        "idle_session_timeout",
                    }
                    else "invalid_session_cookie"
                )
                return None, public_reason
        if settings.oidc_auth_required:
            return None, "missing_authorization"
        request.state.axis_principal = None
        return None, None

    try:
        principal = request.app.state.identity_verifier.verify_authorization_header(authorization)
    except OidcAuthenticationError as exc:
        return None, exc.reason
    _enforce_tenant_admission(request, principal)
    request.state.axis_principal = principal
    return principal, None


def oidc_principal(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> OidcPrincipal | None:
    principal, failure_reason = _resolve_request_principal(request, authorization)
    if principal is not None:
        _annotate_request_span_with_principal(principal)
        _record_request_usage_admission(request, principal)
        return principal
    if failure_reason is None:
        # Explicitly anonymous in a deployment that does not require auth
        # (public demo mode); tenant endpoints authorize reads themselves.
        return None
    cookie_failure_classes = {
        "invalid_session_cookie",
        "revoked_session_cookie",
        "expired_session_cookie",
        "idle_session_timeout",
    }
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": AxisErrorCode.AUTH_REQUIRED.value,
            "message": (
                "The OIDC session cookie could not be verified."
                if failure_reason in cookie_failure_classes
                else "A valid OIDC bearer token is required."
            ),
            "reason": failure_reason,
        },
    )


def _connector_sync_rows(record) -> int:
    """Best-effort extract of the synced row count from a connector run record.

    Reads the ``records_read`` field the sync execution runtime records in its
    ``result_summary`` (stringified). Returns 0 when absent or unparseable so the
    metric never fabricates a count.
    """
    sync_result = getattr(record, "sync_execution_result", None)
    if sync_result is None:
        return 0
    raw = sync_result.result_summary.get("records_read")
    if raw is None:
        return 0
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def _annotate_request_span_with_principal(principal: OidcPrincipal) -> None:
    """Tag the active request span with tenant/actor (non-sensitive ids only)."""
    annotate_current_span(
        {
            ATTR_TENANT_ID: principal.tenant_id,
            ATTR_ACTOR_ID: principal.actor_id,
        }
    )


def _enforce_tenant_admission(request: Request, principal: OidcPrincipal) -> None:
    """Fail closed on an authenticated principal denied by tenant policy.

    This runs where tenant scoping is resolved for every OIDC-bound route: the
    shared principal dependency, covering both bearer tokens and browser session
    cookies. Unauthenticated demo-mode requests carry no verified tenant context
    and are not covered, matching the demo-mode caveat used across the API.
    Status lookups go through the short-TTL tenant state cache, so lifecycle
    changes and newly registered tenants take effect within the documented
    cross-replica staleness window.
    """
    cache: TenantStateCache | None = getattr(request.app.state, "tenant_state_cache", None)
    session_factory = getattr(request.app.state, "session_factory", None)
    if cache is None or session_factory is None:
        return
    try:
        snapshot = cache.snapshot(session_factory, principal.tenant_id)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": AxisErrorCode.CONTROL_PLANE_UNAVAILABLE.value,
                "message": "Tenant admission state is temporarily unavailable.",
                "reason": "tenant_state_unavailable",
            },
        ) from exc
    settings: Settings = request.app.state.settings
    reason = tenant_admission_denial_reason(
        snapshot.status,
        admission_mode=settings.tenant_admission_mode,
    )
    if reason is None:
        return
    tenant_status = snapshot.status or "unregistered"
    with session_scope(session_factory) as session:
        AxisPersistenceRepository(session).append_audit_event(
            AuditEventCreate(
                tenant_id=principal.tenant_id,
                actor_id=principal.actor_id,
                event_type=tenant_admission_denial_audit_event_type(reason),
                payload={
                    "tenant_id": principal.tenant_id,
                    "tenant_status": tenant_status,
                    "reason": reason,
                    "method": request.method,
                    "path": request.url.path,
                    "session_source": principal.session_source,
                },
            )
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": AxisErrorCode.PERMISSION_DENIED.value,
            "message": "The tenant for this request is not active.",
            "reason": reason,
            "tenant_status": tenant_status,
        },
    )


def _fresh_tenant_admission_denial_reason(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    *,
    admission_mode: str,
) -> str | None:
    """Read tenant state directly and return the admission denial reason.

    Session establishment and rotation are low-frequency security boundaries, so
    they read the persisted status directly (bypassing the request-path TTL
    cache) to eliminate the staleness window: a suspension takes effect on the
    very next login or refresh, never up to one TTL later.
    """
    tenant = repository.get_tenant(tenant_id)
    return tenant_admission_denial_reason(
        tenant.status if tenant is not None else None,
        admission_mode=admission_mode,
    )


OIDC_SESSION_BOUNDARY = "http_only_cookie_verified_by_axis_api"
OIDC_SESSION_LIFECYCLE_ACTOR = "axis-session-lifecycle"
IDENTITY_SESSION_ADMIN_SCOPE = "identity:sessions:admin"


class _RotatedSessionCookie(NamedTuple):
    session_cookie_value: str
    session_id: str
    max_age: int


class _SessionRefreshClaim(NamedTuple):
    tenant_id: str
    actor_id: str
    refresh_token: str
    refresh_count: int
    absolute_expires_at: datetime | None


def _refresh_precondition_error(
    *,
    status_code: int,
    reason: str,
    message: str,
    error_code: AxisErrorCode = AxisErrorCode.AUTH_REQUIRED,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": error_code.value, "message": message, "reason": reason},
    )


def _claim_session_refresh(
    request: Request,
    *,
    session_hash: str,
    settings: Settings,
) -> _SessionRefreshClaim | HTTPException:
    """Validate refresh preconditions and atomically claim the transition.

    Runs in its own short transaction and performs no IdP network I/O. Returns a
    claim snapshot (with the decrypted refresh token) for the single winning
    caller, or an ``HTTPException`` describing why the refresh cannot proceed.
    A replayed pre-rotation cookie or a concurrent refresh that lost the claim
    both surface as an ``invalid_session_cookie`` 401.
    """
    with session_scope(request.app.state.session_factory) as session:
        repository = AxisPersistenceRepository(session)
        stored_session = repository.get_oidc_browser_session_by_hash(session_hash)
        if stored_session is None:
            return _refresh_precondition_error(
                status_code=status.HTTP_401_UNAUTHORIZED,
                reason="invalid_session_cookie",
                message="The OIDC session cookie could not be verified.",
            )
        # Fail closed on refresh for a non-active tenant with a fresh status read,
        # revoking the session with distinct audit evidence exactly like any other
        # dead-session refresh precondition. No new session cookie is issued.
        refresh_block_reason = _fresh_tenant_admission_denial_reason(
            repository,
            stored_session.tenant_id,
            admission_mode=settings.tenant_admission_mode,
        )
        if refresh_block_reason is not None:
            if stored_session.status in {"active", "refreshing"}:
                _expire_stored_session(
                    repository,
                    stored_session,
                    revocation_reason=refresh_block_reason,
                )
            return _refresh_precondition_error(
                status_code=status.HTTP_403_FORBIDDEN,
                reason=refresh_block_reason,
                message="The tenant for this session is not active.",
                error_code=AxisErrorCode.PERMISSION_DENIED,
            )
        lifecycle_failure = browser_session_lifecycle_failure(stored_session, settings)
        if lifecycle_failure is not None:
            public_reason, revocation_reason = lifecycle_failure
            if revocation_reason and stored_session.status in {"active", "refreshing"}:
                _expire_stored_session(
                    repository,
                    stored_session,
                    revocation_reason=revocation_reason,
                )
            return _refresh_precondition_error(
                status_code=status.HTTP_401_UNAUTHORIZED,
                reason=public_reason,
                message="The OIDC browser session can no longer be refreshed.",
            )
        if not stored_session.refresh_token_ciphertext:
            return _refresh_precondition_error(
                status_code=status.HTTP_409_CONFLICT,
                reason="refresh_not_available",
                message=(
                    "No refresh token is stored for this session; sign in again to extend it."
                ),
                error_code=AxisErrorCode.CONFLICT,
            )
        # Decrypt before claiming so an unreadable credential does not strand the
        # session in the refreshing state.
        try:
            refresh_token = decrypt_refresh_token(stored_session.refresh_token_ciphertext, settings)
        except OidcTokenExchangeError:
            _expire_stored_session(
                repository,
                stored_session,
                revocation_reason="refresh_failed",
            )
            return _refresh_precondition_error(
                status_code=status.HTTP_401_UNAUTHORIZED,
                reason="refresh_token_unreadable",
                message="The stored OIDC refresh credential could not be read.",
            )
        claim = _SessionRefreshClaim(
            tenant_id=stored_session.tenant_id,
            actor_id=stored_session.actor_id,
            refresh_token=refresh_token,
            refresh_count=stored_session.refresh_count,
            absolute_expires_at=stored_session.absolute_expires_at,
        )
        if not repository.claim_oidc_browser_session_refresh(session_hash):
            # Lost the race to a concurrent refresh (parent already
            # refreshing/rotated), or the cookie is a replayed pre-rotation id.
            return _refresh_precondition_error(
                status_code=status.HTTP_401_UNAUTHORIZED,
                reason="invalid_session_cookie",
                message="The OIDC session cookie could not be verified.",
            )
        return claim


def _expire_stored_session(
    repository: AxisPersistenceRepository,
    stored_session: OidcBrowserSession,
    *,
    revocation_reason: str,
    revoked_by: str = OIDC_SESSION_LIFECYCLE_ACTOR,
) -> None:
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=stored_session.tenant_id,
            actor_id=stored_session.actor_id,
            event_type="identity.oidc_session.revoked",
            payload={
                "session_id_hash": stored_session.session_id_hash,
                "revocation_reason": revocation_reason,
                "session_boundary": OIDC_SESSION_BOUNDARY,
                "federated_logout": False,
            },
        )
    )
    repository.revoke_oidc_browser_session(
        OidcBrowserSessionRevocation(
            session_id_hash=stored_session.session_id_hash,
            revoked_by=revoked_by,
            revocation_reason=revocation_reason,
            revoke_audit_event_id=audit_event.id,
        )
    )


OidcPrincipalDependency = Annotated[
    OidcPrincipal | None,
    Depends(oidc_principal),
]
CheckpointActorScopesQuery = Query(default_factory=list)
CheckpointCreatedAfterQuery = Query(default=None)
CheckpointCreatedBeforeQuery = Query(default=None)
PlatformPolicyScopeQuery = Query(default=None)
TenantLifecycleStatusQuery = Query(default=None, alias="status")
TenantUsageLastDaysQuery = Query(default=7, ge=1, le=366)
TenantUsageFromQuery = Query(default=None, alias="from")
TenantUsageToQuery = Query(default=None, alias="to")
AUDIT_READ_SCOPE = "audit:read"


def _audit_ledger_signer_from_settings(settings: Settings) -> SelfHostedAuditLedgerSigner | None:
    if settings.audit_ledger_signing_secret is None:
        return None
    return SelfHostedAuditLedgerSigner(
        key_id=settings.audit_ledger_signing_key_id,
        secret_key=settings.audit_ledger_signing_secret,
    )


def _oidc_jwks_url(settings: Settings) -> str:
    if settings.oidc_jwks_url:
        return settings.oidc_jwks_url
    return f"{settings.oidc_issuer.rstrip('/')}/protocol/openid-connect/certs"


OIDC_ASYMMETRIC_ALGORITHMS = {
    "RS256",
    "RS384",
    "RS512",
    "ES256",
    "ES384",
    "ES512",
    "PS256",
    "PS384",
    "PS512",
    "EdDSA",
}


def _readiness_check(
    check_id: str,
    ok: bool,
    ready_detail: str,
    action_detail: str,
) -> dict[str, str]:
    return {
        "check_id": check_id,
        "status": "ready" if ok else "action_required",
        "detail": ready_detail if ok else action_detail,
    }


def _oidc_readiness_report(settings: Settings) -> dict[str, object]:
    algorithms = [str(algorithm) for algorithm in settings.oidc_algorithms]
    has_asymmetric_algorithms = bool(algorithms) and all(
        algorithm in OIDC_ASYMMETRIC_ALGORITHMS for algorithm in algorithms
    )
    has_openid_scope = any(
        str(scope).strip().casefold() == "openid" for scope in settings.oidc_scopes
    )
    checks = [
        _readiness_check(
            "auth_required",
            settings.oidc_auth_required,
            "OIDC bearer-token verification is required for protected API paths.",
            "OIDC verification is optional; this is acceptable for local demos only.",
        ),
        _readiness_check(
            "https_issuer",
            settings.oidc_issuer.startswith("https://"),
            "OIDC issuer uses HTTPS.",
            "OIDC issuer is not HTTPS; use a TLS issuer for enterprise SSO.",
        ),
        _readiness_check(
            "explicit_jwks_url",
            bool(settings.oidc_jwks_url),
            "JWKS URL is explicitly configured.",
            "JWKS URL is derived from the issuer; configure it explicitly for enterprise SSO.",
        ),
        _readiness_check(
            "asymmetric_algorithms",
            has_asymmetric_algorithms,
            "OIDC verifier accepts asymmetric signing algorithms only.",
            "OIDC verifier must use asymmetric signing algorithms for enterprise SSO.",
        ),
        _readiness_check(
            "openid_scope",
            has_openid_scope,
            "OIDC authorization-code scope includes openid for ID-token issuance.",
            "Configure AXIS_OIDC_SCOPES to include openid before browser SSO.",
        ),
        _readiness_check(
            "tenant_claim",
            bool(settings.oidc_tenant_claim),
            "Tenant claim binding is configured.",
            "Tenant claim binding is missing.",
        ),
        _readiness_check(
            "actor_claim",
            bool(settings.oidc_actor_claim),
            "Actor claim binding is configured.",
            "Actor claim binding is missing.",
        ),
        _readiness_check(
            "authorization_code_client",
            bool(settings.oidc_client_id),
            "OIDC authorization-code client id is configured.",
            "Configure AXIS_OIDC_CLIENT_ID before using enterprise browser SSO.",
        ),
        _readiness_check(
            "authorization_endpoint",
            authorization_endpoint(settings).startswith("https://"),
            "OIDC authorization endpoint uses HTTPS.",
            "OIDC authorization endpoint must use HTTPS for enterprise SSO.",
        ),
        _readiness_check(
            "token_endpoint",
            token_endpoint(settings).startswith("https://"),
            "OIDC token endpoint uses HTTPS.",
            "OIDC token endpoint must use HTTPS for enterprise SSO.",
        ),
        _readiness_check(
            "end_session_endpoint",
            bool(settings.oidc_end_session_url)
            and end_session_endpoint(settings).startswith("https://"),
            "OIDC end-session endpoint is explicitly configured and uses HTTPS.",
            "Configure AXIS_OIDC_END_SESSION_URL with a TLS end-session endpoint.",
        ),
        _readiness_check(
            "post_logout_redirect",
            post_logout_redirect_uri(settings, "/").startswith("https://"),
            "Post-logout redirect URI uses HTTPS.",
            "Configure AXIS_OIDC_POST_LOGOUT_REDIRECT_URI or AXIS_PUBLIC_BASE_URL with HTTPS.",
        ),
        _readiness_check(
            "session_cookie_signing",
            bool(settings.oidc_session_cookie_signing_secret),
            "OIDC session cookies are signed with an operator-provided key.",
            "Configure the OIDC session-cookie signing setting before browser SSO.",
        ),
        _readiness_check(
            "secure_session_cookie",
            settings.oidc_session_cookie_secure,
            "OIDC session cookie uses the Secure attribute.",
            "Enable AXIS_OIDC_SESSION_COOKIE_SECURE for enterprise browser SSO.",
        ),
        _readiness_check(
            "host_prefixed_session_cookie",
            settings.oidc_session_cookie_secure and settings.oidc_session_cookie_host_prefix,
            "OIDC session cookie uses the __Host- prefix binding.",
            "Enable Secure cookies plus AXIS_OIDC_SESSION_COOKIE_HOST_PREFIX for __Host- binding.",
        ),
        _readiness_check(
            "refresh_credential_encryption",
            refresh_token_encryption_key_is_strong(settings),
            "OIDC refresh credentials are encrypted at rest with an HKDF-derived key.",
            "Configure a refresh-credential encryption key of at least 32 characters "
            "before session refresh.",
        ),
        _readiness_check(
            "session_idle_timeout",
            settings.oidc_session_idle_timeout_seconds > 0,
            "Browser sessions enforce an idle timeout.",
            "Set AXIS_OIDC_SESSION_IDLE_TIMEOUT_SECONDS above zero for production sessions.",
        ),
        _readiness_check(
            "session_absolute_timeout",
            settings.oidc_session_absolute_timeout_seconds > 0,
            "Browser sessions enforce an absolute lifetime cap.",
            "Set AXIS_OIDC_SESSION_ABSOLUTE_TIMEOUT_SECONDS above zero for production sessions.",
        ),
    ]
    enterprise_ready = all(check["status"] == "ready" for check in checks)
    return {
        "status": "ready" if enterprise_ready else "action_required",
        "enterprise_sso_ready": enterprise_ready,
        "auth_required": settings.oidc_auth_required,
        "issuer": settings.oidc_issuer,
        "audience": settings.oidc_audience,
        "jwks_source": "configured" if settings.oidc_jwks_url else "derived_from_issuer",
        "jwks_url_configured": bool(settings.oidc_jwks_url),
        "jwks_cache_seconds": settings.oidc_jwks_cache_seconds,
        "federated_logout": {
            "end_session_source": (
                "configured" if settings.oidc_end_session_url else "derived_from_issuer"
            ),
            "end_session_url_configured": bool(settings.oidc_end_session_url),
            "post_logout_redirect_uri": post_logout_redirect_uri(settings, "/"),
            "stores_provider_logout_tokens": False,
        },
        "session_lifecycle": {
            "idle_timeout_seconds": settings.oidc_session_idle_timeout_seconds,
            "absolute_timeout_seconds": settings.oidc_session_absolute_timeout_seconds,
            "max_concurrent_sessions": settings.oidc_session_max_concurrent,
            "refresh_credential_encryption_configured": bool(
                settings.oidc_refresh_token_encryption_key
            ),
            "refresh_rotation": "server_side_rotating_sessions",
            "csrf_protection": "hmac_double_submit_header",
            "host_prefixed_session_cookie": (
                settings.oidc_session_cookie_secure and settings.oidc_session_cookie_host_prefix
            ),
        },
        "algorithms": algorithms,
        "token_binding": {
            "actor_claim": settings.oidc_actor_claim,
            "tenant_claim": settings.oidc_tenant_claim,
            "scope_sources": [
                "scope",
                "scp",
                "realm_access.roles",
                f"resource_access[{settings.oidc_audience}].roles",
            ],
        },
        "checks": checks,
    }


def _oidc_readiness_summary(settings: Settings) -> dict[str, object]:
    report = _oidc_readiness_report(settings)
    return {
        "oidc_auth_required": report["auth_required"],
        "enterprise_sso_ready": report["enterprise_sso_ready"],
        "readiness_status": report["status"],
    }


DEMO_TENANT_ID = "tenant_demo_manufacturing"


def _actor_binding_http_exception(exc: ActorBindingError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": AxisErrorCode.PERMISSION_DENIED.value,
            "message": exc.message,
            "reason": exc.reason,
        },
    )


def _bind_tenant_actor(
    request_model,
    principal: OidcPrincipal | None,
    tenant_id: str,
):
    if principal is None and tenant_id != DEMO_TENANT_ID:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": AxisErrorCode.AUTH_REQUIRED.value,
                "message": "Authentication is required outside the demo tenant.",
                "reason": "authentication_required",
            },
        )
    try:
        return bind_request_actor(
            request_model,
            principal,
            expected_tenant_id=tenant_id,
        )
    except ActorBindingError as exc:
        raise _actor_binding_http_exception(exc) from exc


def _bind_demo_actor(request_model, principal: OidcPrincipal | None):
    return _bind_tenant_actor(request_model, principal, DEMO_TENANT_ID)


def _bind_demo_tenant_actor(request_model, principal: OidcPrincipal | None):
    """Bind a demo request that also carries a ``tenant_id`` field.

    ``_bind_demo_actor`` pins the principal to the demo tenant and overwrites
    the actor identity; this variant additionally rejects a request body whose
    ``tenant_id`` differs from the authenticated principal's tenant, so a bound
    write can never land in another tenant's scope (same ``tenant_mismatch``
    contract as ``_bind_body_tenant_actor``).
    """
    bound_request = _bind_demo_actor(request_model, principal)
    if principal is not None and getattr(bound_request, "tenant_id", None) != (principal.tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": AxisErrorCode.PERMISSION_DENIED.value,
                "message": "The authenticated OIDC tenant cannot access this tenant scope.",
                "reason": "tenant_mismatch",
            },
        )
    return bound_request


def _bind_audit_actor(request_model, principal: OidcPrincipal | None):
    try:
        return bind_request_actor(request_model, principal, actor_field="actor_id")
    except ActorBindingError as exc:
        raise _actor_binding_http_exception(exc) from exc


def _scope_denial_http_exception(
    exc: ScopeAuthorizationError,
    *,
    default_required_permission: str | None = None,
) -> HTTPException:
    decision_reason = exc.decision.reason
    tenant_mismatch = decision_reason == TENANT_MISMATCH_REASON
    if decision_reason.startswith("missing_scope:"):
        required_permission = decision_reason.removeprefix("missing_scope:")
        reason = "missing_required_scope"
    else:
        required_permission = default_required_permission or exc.required_scopes[0]
        reason = (
            "missing_required_scope"
            if decision_reason.startswith("missing_relationship_scope:")
            else decision_reason
        )
    detail: dict[str, object] = {
        "code": AxisErrorCode.PERMISSION_DENIED.value,
        "message": exc.message,
        "required_permission": required_permission,
        "reason": reason,
    }
    # Cross-tenant denials predate the permission_reason evidence field; the
    # extra key stays absent there so existing denial contracts are stable.
    if not tenant_mismatch:
        detail["permission_reason"] = decision_reason
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=detail,
    )


def _authorize_audit_scope(
    *,
    tenant_id: str,
    principal: OidcPrincipal | None,
    required_scope: str,
    message: str,
    resource: str,
) -> None:
    try:
        authorize_principal_scopes(
            tenant_id=tenant_id,
            principal=principal,
            required_scopes=[required_scope],
            attributes={"surface": "audit", "resource": resource},
            message=message,
        )
    except ScopeAuthorizationError as exc:
        raise _scope_denial_http_exception(exc) from exc


def _run_object_legal_hold(
    operation,
    repository,
    object_store,
    request: AuditObjectLegalHoldRequest,
) -> AuditObjectLegalHoldRecord:
    try:
        return operation(repository, object_store, request)
    except AuditLegalHoldPermissionDenied as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": AxisErrorCode.PERMISSION_DENIED.value,
                "message": "The actor cannot manage object-store legal holds.",
                "required_permissions": [LEGAL_HOLD_REQUIRED_SCOPE],
                "reason": exc.decision.reason,
            },
        ) from exc
    except AuditExportWormEnforcementError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": AxisErrorCode.CONNECTOR_UNAVAILABLE.value,
                "message": (
                    "The configured object store cannot enforce S3 object-lock legal holds."
                ),
                "reason": exc.reason,
            },
        ) from exc


def _bind_demo_field_actor(
    request_model,
    principal: OidcPrincipal | None,
    actor_field: str,
):
    """Bind a demo write whose actor identity lives in ``actor_field``."""
    try:
        return bind_request_actor(
            request_model,
            principal,
            actor_field=actor_field,
            expected_tenant_id=DEMO_TENANT_ID,
        )
    except ActorBindingError as exc:
        raise _actor_binding_http_exception(exc) from exc


def _bind_demo_created_by(request_model, principal: OidcPrincipal | None):
    return _bind_demo_field_actor(request_model, principal, "created_by")


def _bind_demo_enabled_by(request_model, principal: OidcPrincipal | None):
    return _bind_demo_field_actor(request_model, principal, "enabled_by")


def _bind_demo_updated_by(request_model, principal: OidcPrincipal | None):
    return _bind_demo_field_actor(request_model, principal, "updated_by")


def _platform_policy_denied_detail(exc: PlatformPolicyEnforcementDenied, message: str) -> dict:
    return {
        "code": AxisErrorCode.POLICY_VIOLATION.value,
        "message": message,
        "reason": "platform_policy_denied",
        "policy_id": exc.decision.matched_policy_id,
        "policy_revision_number": exc.decision.matched_revision_number,
        "policy_version": exc.decision.matched_policy_version,
        "audit_event_id": str(exc.audit_event_id),
        "audit_event_type": exc.audit_event_type,
    }


def _bind_body_tenant_actor(
    request_model,
    principal: OidcPrincipal | None,
    actor_field: str,
    *,
    tenant_mismatch_message: str = TENANT_MISMATCH_MESSAGE,
) -> object:
    """Bind a write whose governing tenant is declared in the request body."""
    try:
        return bind_request_actor(
            request_model,
            principal,
            actor_field=actor_field,
            tenant_mismatch_message=tenant_mismatch_message,
        )
    except ActorBindingError as exc:
        raise _actor_binding_http_exception(exc) from exc


def _authorize_scopes_for_tenant(
    *,
    tenant_id: str,
    principal: OidcPrincipal | None,
    required_scope: str,
    surface: str,
    resource: str,
    message: str,
) -> None:
    try:
        authorize_principal_scopes(
            tenant_id=tenant_id,
            principal=principal,
            required_scopes=[required_scope],
            attributes={"surface": surface, "resource": resource},
            message=message,
        )
    except ScopeAuthorizationError as exc:
        raise _scope_denial_http_exception(exc) from exc


def _authorize_platform_policy_read(
    *,
    tenant_id: str,
    principal: OidcPrincipal | None,
    resource: str,
) -> None:
    _authorize_scopes_for_tenant(
        tenant_id=tenant_id,
        principal=principal,
        required_scope=PLATFORM_POLICY_READ_SCOPE,
        surface="platform_policies",
        resource=resource,
        message="The actor cannot read platform policies.",
    )


def _authorize_model_endpoint_read(
    *,
    tenant_id: str,
    principal: OidcPrincipal | None,
    resource: str,
) -> None:
    _authorize_scopes_for_tenant(
        tenant_id=tenant_id,
        principal=principal,
        required_scope=MODEL_ENDPOINT_READ_SCOPE,
        surface="model_endpoints",
        resource=resource,
        message="The actor cannot read the model routing surface.",
    )


def _bind_platform_tenant_actor(request_model, principal: OidcPrincipal | None):
    """Bind the operator identity for the cross-tenant platform-tenant surface.

    Tenant lifecycle routes are a platform-operator surface: the operator
    authenticates under their own tenant and acts on other tenants, so there is
    deliberately no principal-tenant match check here. Cross-tenant authority is
    gated by the dedicated ``platform:tenant:*`` operator scopes evaluated in
    the service layer. Actor impersonation is still rejected.
    """
    if principal is None:
        return request_model

    request_actor = getattr(request_model, "requested_by", None)
    if request_actor and request_actor != principal.actor_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": AxisErrorCode.PERMISSION_DENIED.value,
                "message": ACTOR_MISMATCH_MESSAGE,
                "reason": "actor_mismatch",
            },
        )

    return request_model.model_copy(
        update={
            "requested_by": principal.actor_id,
            "actor_scopes": principal.scopes,
        }
    )


def _authorize_cross_tenant_operator_scopes(
    principal: OidcPrincipal | None,
    *,
    required_scopes: list[str],
    surface: str,
    resource: str,
    message: str,
    fallback_required_scope: str,
) -> None:
    """Gate a platform-operator read with operator scopes, no tenant binding.

    The operator acts from their own tenant, so the evaluated tenant is the
    principal's own and cross-tenant authority comes from the dedicated
    ``platform:*`` scopes alone.
    """
    if principal is None:
        return

    try:
        authorize_principal_scopes(
            tenant_id=principal.tenant_id,
            principal=principal,
            required_scopes=required_scopes,
            attributes={"surface": surface, "resource": resource},
            message=message,
            bind_tenant=False,
        )
    except ScopeAuthorizationError as exc:
        raise _scope_denial_http_exception(
            exc,
            default_required_permission=fallback_required_scope,
        ) from exc


def _authorize_platform_tenant_read(
    principal: OidcPrincipal | None,
    *,
    resource: str,
) -> None:
    _authorize_cross_tenant_operator_scopes(
        principal,
        required_scopes=[PLATFORM_TENANT_OPERATOR_SCOPE, PLATFORM_TENANT_READ_SCOPE],
        surface="platform_tenants",
        resource=resource,
        message="The actor cannot read platform tenants.",
        fallback_required_scope=PLATFORM_TENANT_READ_SCOPE,
    )


def _authorize_platform_tenant_usage_read(
    principal: OidcPrincipal | None,
    *,
    resource: str,
) -> None:
    """Authorize the operator-scoped usage read.

    Usage is a billing-adjacent read: it requires the platform operator scope
    plus a dedicated ``platform:tenant:usage`` scope, following the same
    cross-tenant operator convention as the rest of the platform-tenant surface
    (the operator authenticates under their own tenant and reads any tenant's
    consumption). Demo/offline mode (no principal) is intentionally not gated.
    """
    _authorize_cross_tenant_operator_scopes(
        principal,
        required_scopes=[PLATFORM_TENANT_OPERATOR_SCOPE, PLATFORM_TENANT_USAGE_SCOPE],
        surface="platform_tenant_usage",
        resource=resource,
        message="The actor cannot read platform tenant usage.",
        fallback_required_scope=PLATFORM_TENANT_USAGE_SCOPE,
    )


def _platform_tenant_denied_http_exception(
    exc: TenantPermissionDenied,
    message: str,
) -> HTTPException:
    reason = (
        "missing_required_scope"
        if exc.decision.reason.startswith("missing_scope:")
        else exc.decision.reason
    )
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": AxisErrorCode.PERMISSION_DENIED.value,
            "message": message,
            "required_permission": exc.required_permission,
            "reason": reason,
            "permission_reason": exc.decision.reason,
        },
    )


def _platform_tenant_not_found_http_exception(tenant_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": AxisErrorCode.NOT_FOUND.value,
            "message": "The tenant was not found.",
            "tenant_id": tenant_id,
        },
    )


def _platform_tenant_lifecycle_conflict_http_exception(
    exc: TenantLifecycleConflict,
) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": AxisErrorCode.CONFLICT.value,
            "message": "The tenant lifecycle transition conflicts with the current status.",
            "reason": exc.reason,
            "tenant_id": exc.tenant_id,
        },
    )


def _bind_demo_activated_by(request_model, principal: OidcPrincipal | None):
    return _bind_demo_field_actor(request_model, principal, "activated_by")


def _bind_demo_requested_by(request_model, principal: OidcPrincipal | None):
    """Bind a demo write whose ``requested_by`` actor carries a tenant scope.

    The principal must be demo-bound *and* a body that names a foreign
    ``tenant_id`` is rejected even then (same contract as
    ``_bind_demo_tenant_actor``).
    """
    if principal is not None and (
        getattr(request_model, "tenant_id", DEMO_TENANT_ID) != DEMO_TENANT_ID
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": AxisErrorCode.PERMISSION_DENIED.value,
                "message": TENANT_MISMATCH_MESSAGE,
                "reason": TENANT_MISMATCH_REASON,
            },
        )
    try:
        return bind_request_actor(
            request_model,
            principal,
            actor_field="requested_by",
            expected_tenant_id=DEMO_TENANT_ID,
        )
    except ActorBindingError as exc:
        raise _actor_binding_http_exception(exc) from exc


def _ontology_read_denied_http_exception(
    exc: OntologyReadPermissionDenied,
) -> HTTPException:
    detail: dict[str, object] = {
        "code": AxisErrorCode.PERMISSION_DENIED.value,
        "message": exc.message,
        "reason": exc.decision.reason,
    }
    if exc.required_permissions:
        detail["required_permissions"] = exc.required_permissions
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _authorize_connector_sync_checkpoint_read(
    tenant_id: str,
    actor_scopes: list[str],
    principal: OidcPrincipal | None,
) -> None:
    try:
        authorize_principal_scopes(
            tenant_id=tenant_id,
            principal=principal,
            required_scopes=[SYNC_CHECKPOINT_READ_SCOPE],
            attributes={
                "surface": "connectors",
                "resource": "connector_sync_checkpoints",
            },
            message="The actor cannot read connector sync checkpoints.",
            tenant_mismatch_message=(
                "The authenticated OIDC tenant cannot access connector checkpoints."
            ),
            actor_fallback_id="connector-sync-checkpoint-reader",
            scope_fallback=actor_scopes,
        )
    except ScopeAuthorizationError as exc:
        raise _scope_denial_http_exception(exc) from exc


def _authorize_connector_sync_checkpoint_claim_read(
    tenant_id: str,
    actor_scopes: list[str],
    principal: OidcPrincipal | None,
) -> None:
    try:
        authorize_principal_scopes(
            tenant_id=tenant_id,
            principal=principal,
            required_scopes=[SYNC_CHECKPOINT_CLAIM_READ_SCOPE],
            attributes={
                "surface": "connectors",
                "resource": "connector_sync_checkpoint_claims",
            },
            message="The actor cannot read connector sync checkpoint claims.",
            tenant_mismatch_message=(
                "The authenticated OIDC tenant cannot access connector checkpoint claims."
            ),
            actor_fallback_id="connector-sync-checkpoint-claim-reader",
            scope_fallback=actor_scopes,
        )
    except ScopeAuthorizationError as exc:
        raise _scope_denial_http_exception(exc) from exc


def _authorize_source_ingestion_read(
    principal: OidcPrincipal | None,
    actor_scopes: list[str],
    *,
    operation: str,
) -> None:
    resolved_scopes = principal.scopes if principal is not None else actor_scopes
    if SOURCE_INGESTION_READ_SCOPE in resolved_scopes:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": AxisErrorCode.PERMISSION_DENIED.value,
            "message": (
                "The actor lacks the source ingestion read scope required to "
                f"{operation}."
            ),
            "required_permission": SOURCE_INGESTION_READ_SCOPE,
            "reason": f"missing_scope:{SOURCE_INGESTION_READ_SCOPE}",
        },
    )


def _authorize_tenant_read(
    tenant_id: str,
    principal: OidcPrincipal | None,
) -> None:
    """Bind any tenant-scoped read to the verified principal when present."""

    if principal is not None and principal.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": AxisErrorCode.PERMISSION_DENIED.value,
                "message": TENANT_MISMATCH_MESSAGE,
                "reason": TENANT_MISMATCH_REASON,
            },
        )


def _bind_connector_run_actor(
    request_model,
    principal: OidcPrincipal | None,
    *,
    actor_field: str,
):
    return _bind_body_tenant_actor(
        request_model,
        principal,
        actor_field,
        tenant_mismatch_message=(
            "The authenticated OIDC tenant cannot access this connector run scope."
        ),
    )


def _usage_metering_projection_loop(
    app: FastAPI,
    stop: Event,
) -> None:
    """Continuously project durable usage events into the rollup read model."""

    settings = app.state.settings
    projector: UsageEventProjector = app.state.usage_event_projector
    session_factory = app.state.session_factory
    while not stop.is_set():
        try:
            result = projector.project_available(
                session_factory,
                batch_size=settings.usage_metering_projection_batch_size,
                max_batches=settings.usage_metering_projection_max_batches_per_tick,
            )
            if result.events_projected:
                _LOGGER.debug(
                    "Usage projector folded %s events.",
                    result.events_projected,
                )
        except Exception:  # noqa: BLE001 - a flush error must not kill the loop
            _LOGGER.warning(
                "Usage event projection failed; journal rows remain pending.",
                exc_info=True,
            )
        delay = projector.retry_delay_seconds(settings.usage_metering_flush_interval_seconds)
        stop.wait(timeout=delay)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    _warm_audit_export_object_lock_capability(app)
    projection_thread: Thread | None = None
    projection_stop = Event()
    if app.state.settings.usage_metering_enabled:
        projection_thread = Thread(
            target=_usage_metering_projection_loop,
            args=(app, projection_stop),
            name="axis-usage-projector",
            daemon=True,
        )
        projection_thread.start()
    try:
        yield
    finally:
        if projection_thread is not None:
            projection_stop.set()
            projection_thread.join(
                timeout=app.state.settings.usage_metering_shutdown_timeout_seconds
            )
            if projection_thread.is_alive():
                _LOGGER.warning(
                    "Usage event projector exceeded its shutdown deadline; "
                    "journal rows remain durable for another replica or restart."
                )
        runtime: TelemetryRuntime | None = getattr(app.state, "telemetry", None)
        if runtime is not None and runtime.enabled:
            shutdown_providers(runtime.tracer_provider, runtime.meter_provider)
        await app.state.rate_limit_backend.close()


def create_app(
    settings: Settings | None = None,
    *,
    telemetry: TelemetryRuntime | None = None,
    readiness_service: RuntimeReadinessService | None = None,
    rate_limit_backend: RateLimitBackend | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()
    validate_runtime_configuration(resolved_settings)
    production = resolved_settings.environment.strip().casefold() in {
        "prod",
        "production",
    }
    app = FastAPI(
        title="Limes Axis API",
        description="Core API for the sovereign AI control plane for European operations.",
        version="0.0.0",
        license_info={
            "name": "Apache-2.0",
            "url": "https://www.apache.org/licenses/LICENSE-2.0.html",
        },
        docs_url=None if production else "/docs",
        redoc_url=None if production else "/redoc",
        openapi_url=None if production else "/openapi.json",
        lifespan=_lifespan,
    )
    operations_router = APIRouter()
    # The data plane is a first-class surface: it stays outside the demo
    # namespace and never receives the legacy /demo/manufacturing alias.
    data_router = APIRouter(tags=["data"])

    @app.exception_handler(ManufacturingTenantNotFound)
    async def manufacturing_tenant_not_found_handler(
        _request: Request,
        exc: ManufacturingTenantNotFound,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "detail": {
                    "code": AxisErrorCode.TENANT_NOT_FOUND.value,
                    "message": "The manufacturing tenant is unknown.",
                    "tenant_id": exc.tenant_id,
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        # Starlette's ServerErrorMiddleware sits outside user middleware. Its
        # default 500 response therefore bypasses request-correlation and CORS
        # response processing unless the application-level error handler carries
        # that evidence explicitly.
        request_id = getattr(request.state, "request_id", None) or new_request_id()
        _LOGGER.error(
            "Unhandled API request failed request_id=%s exception_type=%s",
            request_id,
            type(exc).__name__,
        )
        headers = {REQUEST_ID_HEADER: request_id}
        origin = request.headers.get("origin")
        if origin and (
            "*" in resolved_settings.cors_origins or origin in resolved_settings.cors_origins
        ):
            headers.update(
                {
                    "Access-Control-Allow-Credentials": "true",
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Expose-Headers": REQUEST_ID_HEADER,
                    "Vary": "Origin",
                }
            )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal Server Error"},
            headers=headers,
        )

    validate_refresh_token_encryption_key(resolved_settings)
    app.add_middleware(BrowserSessionCsrfMiddleware, settings=resolved_settings)
    resolved_rate_limit_backend = rate_limit_backend or build_rate_limit_backend(resolved_settings)
    app.add_middleware(
        ApiRateLimitMiddleware,
        settings=resolved_settings,
        backend=resolved_rate_limit_backend,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Cache-Control",
            "Content-Type",
            "X-Axis-Tenant",
            "X-Axis-Actor",
            "X-Axis-Csrf-Token",
            REQUEST_ID_HEADER,
        ],
        expose_headers=[REQUEST_ID_HEADER],
    )
    app.add_middleware(RequestCorrelationMiddleware)
    app.state.settings = resolved_settings
    app.state.rate_limit_backend = resolved_rate_limit_backend
    telemetry = telemetry or configure_api_telemetry(resolved_settings)
    app.state.telemetry = telemetry
    instrument_fastapi_app(app, telemetry)
    app.state.session_factory = create_session_factory(resolved_settings)
    app.state.tenant_state_cache = TenantStateCache(
        ttl_seconds=resolved_settings.tenant_state_cache_ttl_seconds,
    )
    app.state.request_usage_admission_recorder = RequestUsageAdmissionRecorder(
        enabled=resolved_settings.usage_metering_enabled,
        window_seconds=resolved_settings.usage_metering_aggregation_window_seconds,
        statement_timeout_ms=(resolved_settings.usage_metering_admission_statement_timeout_ms),
    )
    app.state.usage_event_projector = UsageEventProjector(
        failure_threshold=(resolved_settings.usage_metering_projection_failure_threshold),
        max_backlog_age_seconds=(
            resolved_settings.usage_metering_projection_max_backlog_age_seconds
        ),
    )
    app.state.workflow_runtime = (
        TemporalWorkflowSignalRuntime(
            TemporalWorkflowSignalConfig(
                address=resolved_settings.temporal_address,
                namespace=resolved_settings.temporal_namespace,
                signal_timeout_seconds=resolved_settings.temporal_signal_timeout_seconds,
            )
        )
        if resolved_settings.workflow_signals_enabled
        else DeferredWorkflowSignalRuntime()
    )
    app.state.runtime_readiness_service = readiness_service or build_runtime_readiness_service(
        resolved_settings,
        session_factory=app.state.session_factory,
        workflow_runtime=app.state.workflow_runtime,
        usage_event_projector=app.state.usage_event_projector,
    )
    app.state.ontology_mutation_runtime = (
        TypeDBOntologyMutationRuntime(
            TypeDBOntologyMutationConfig(
                address=resolved_settings.typedb_address,
                username=resolved_settings.typedb_username,
                password=resolved_settings.typedb_password,
                database=resolved_settings.typedb_database,
            )
        )
        if resolved_settings.ontology_mutations_enabled
        else DeferredOntologyMutationRuntime()
    )
    app.state.ontology_query_runtime = (
        TypeDBOntologyQueryRuntime(
            TypeDBOntologyQueryConfig(
                address=resolved_settings.typedb_address,
                username=resolved_settings.typedb_username,
                password=resolved_settings.typedb_password,
                database=resolved_settings.typedb_database,
            )
        )
        if resolved_settings.ontology_queries_enabled
        else DeferredOntologyQueryRuntime()
    )
    app.state.connector_execution_runtime = DeferredConnectorExecutionRuntime()
    app.state.connector_sync_scheduler_runtime = DeferredConnectorSyncSchedulerRuntime()
    app.state.connector_sync_dispatch_runtime = DeferredConnectorSyncDispatchRuntime()
    app.state.connector_sync_execution_runtime = connector_sync_execution_runtime_from_settings(
        resolved_settings
    )
    app.state.connector_live_sync_runtime = connector_live_sync_runtime_from_settings(
        resolved_settings
    )
    app.state.connector_source_discovery_runtime = connector_source_discovery_runtime_from_settings(
        resolved_settings
    )
    if resolved_settings.credential_lease_provider_adapters_enabled:
        app.state.credential_lease_runtime = ProviderSpecificVaultKmsLeaseRuntime()
    elif resolved_settings.credential_lease_execution_enabled:
        app.state.credential_lease_runtime = SelfHostedVaultKmsLeaseRuntime()
    else:
        app.state.credential_lease_runtime = DeferredCredentialLeaseRuntime()
    app.state.model_invocation_runtime = (
        SelfHostedOpenAICompatibleRuntime(
            timeout_seconds=resolved_settings.model_invocation_timeout_seconds,
            allowed_base_urls=resolved_settings.model_invocation_allowed_base_urls,
        )
        if resolved_settings.model_routing_execution_enabled
        else DeferredModelInvocationRuntime()
    )
    app.state.identity_verifier = RemoteJwksOidcVerifier(
        issuer=resolved_settings.oidc_issuer,
        audience=resolved_settings.oidc_audience,
        algorithms=resolved_settings.oidc_algorithms,
        jwks_url=_oidc_jwks_url(resolved_settings),
        cache_seconds=resolved_settings.oidc_jwks_cache_seconds,
        actor_claim=resolved_settings.oidc_actor_claim,
        tenant_claim=resolved_settings.oidc_tenant_claim,
    )
    app.state.oidc_token_exchanger = exchange_authorization_code

    app.include_router(
        build_system_router(
            identity_summary=lambda: _oidc_readiness_summary(resolved_settings),
            external_model_egress_enabled=resolved_settings.external_model_egress_enabled,
        )
    )

    @app.get("/identity/oidc/readiness", tags=["system"])
    def oidc_readiness() -> dict[str, object]:
        return _oidc_readiness_report(resolved_settings)

    @app.get("/identity/oidc/onboarding", response_model=OidcOnboardingReport, tags=["system"])
    def oidc_onboarding() -> OidcOnboardingReport:
        return build_oidc_onboarding_report(
            resolved_settings,
            oidc_readiness_report=_oidc_readiness_report(resolved_settings),
        )

    @app.get("/identity/oidc/authorize", tags=["system"])
    def oidc_authorize(return_to: str = "/") -> RedirectResponse:
        try:
            authorization_request = build_authorization_request(resolved_settings, return_to)
        except OidcCodeFlowConfigurationError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": AxisErrorCode.AUTH_REQUIRED.value,
                    "message": "OIDC authorization-code login is not configured.",
                    "reason": exc.reason,
                },
            ) from exc

        response = RedirectResponse(
            authorization_request.authorization_url,
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )
        response.set_cookie(
            resolved_settings.oidc_login_cookie_name,
            authorization_request.login_cookie_value,
            max_age=authorization_request.max_age_seconds,
            httponly=True,
            secure=resolved_settings.oidc_session_cookie_secure,
            samesite="lax",
            path="/identity/oidc",
        )
        return response

    def delete_oidc_session_cookie(response: Response) -> None:
        response.delete_cookie(
            session_cookie_name(resolved_settings),
            path="/",
            secure=resolved_settings.oidc_session_cookie_secure,
            httponly=True,
            samesite="lax",
        )
        response.delete_cookie(
            csrf_cookie_name(resolved_settings),
            path="/",
            secure=resolved_settings.oidc_session_cookie_secure,
            httponly=False,
            samesite="lax",
        )

    def set_oidc_session_cookies(
        response: Response,
        *,
        session_cookie_value: str,
        session_id: str,
        max_age: int,
    ) -> None:
        response.set_cookie(
            session_cookie_name(resolved_settings),
            session_cookie_value,
            max_age=max_age,
            httponly=True,
            secure=resolved_settings.oidc_session_cookie_secure,
            samesite="lax",
            path="/",
        )
        response.set_cookie(
            csrf_cookie_name(resolved_settings),
            csrf_token_for_session(session_id, resolved_settings),
            max_age=max_age,
            httponly=False,
            secure=resolved_settings.oidc_session_cookie_secure,
            samesite="lax",
            path="/",
        )

    def revoke_oidc_session_from_cookie(
        request: Request,
        *,
        revocation_reason: str,
        federated_logout: bool,
    ) -> None:
        session_cookie = request.cookies.get(session_cookie_name(resolved_settings))
        if not session_cookie:
            return

        try:
            oidc_session = read_session_cookie(session_cookie, resolved_settings)
            session_hash = session_id_hash(oidc_session.session_id, resolved_settings)
        except (OidcCodeFlowConfigurationError, OidcCookieValidationError):
            return

        with session_scope(request.app.state.session_factory) as session:
            repository = AxisPersistenceRepository(session)
            stored_session = repository.get_oidc_browser_session_by_hash(session_hash)
            if stored_session is None or stored_session.status == "revoked":
                return
            audit_event = repository.append_audit_event(
                AuditEventCreate(
                    tenant_id=stored_session.tenant_id,
                    actor_id=stored_session.actor_id,
                    event_type="identity.oidc_session.revoked",
                    payload={
                        "session_id_hash": session_hash,
                        "revocation_reason": revocation_reason,
                        "session_boundary": "http_only_cookie_verified_by_axis_api",
                        "federated_logout": federated_logout,
                    },
                )
            )
            repository.revoke_oidc_browser_session(
                OidcBrowserSessionRevocation(
                    session_id_hash=session_hash,
                    revoked_by=stored_session.actor_id,
                    revocation_reason=revocation_reason,
                    revoke_audit_event_id=audit_event.id,
                )
            )

    def record_oidc_login_failure(
        request: Request,
        *,
        reason: str,
        principal: OidcPrincipal | None,
    ) -> None:
        with session_scope(request.app.state.session_factory) as session:
            repository = AxisPersistenceRepository(session)
            repository.append_audit_event(
                AuditEventCreate(
                    tenant_id=principal.tenant_id if principal else "tenant_unattributed",
                    actor_id=principal.actor_id if principal else "browser_unauthenticated",
                    event_type="identity.oidc_login.failed",
                    payload={
                        "reason": reason,
                        "flow": "authorization_code_pkce",
                        "session_boundary": OIDC_SESSION_BOUNDARY,
                    },
                )
            )

    @app.get("/identity/oidc/callback", tags=["system"])
    def oidc_callback(request: Request, code: str, state: str) -> RedirectResponse:
        principal: OidcPrincipal | None = None
        try:
            login_state = read_login_state(
                request.cookies.get(resolved_settings.oidc_login_cookie_name),
                resolved_settings,
            )
            if login_state.state != state:
                raise OidcCookieValidationError("oidc_state_mismatch")
            form = build_token_exchange_form(
                settings=resolved_settings,
                code=code,
                login_state=login_state,
            )
            token_response = request.app.state.oidc_token_exchanger(form, resolved_settings)
            access_token = token_response.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise OidcTokenExchangeError("missing_access_token")
            id_token = token_response.get("id_token")
            if not isinstance(id_token, str) or not id_token:
                raise OidcTokenExchangeError("missing_id_token")
            principal = request.app.state.identity_verifier.verify_authorization_header(
                f"Bearer {access_token}"
            )
            id_token_claims = request.app.state.identity_verifier.verify_id_token(
                id_token,
                client_id=resolved_settings.oidc_client_id or "",
                nonce=login_state.nonce,
                access_token=access_token,
            )
            if id_token_claims.get("sub") != principal.subject_id:
                raise OidcAuthenticationError("id_token_subject_mismatch")
            absolute_timeout_seconds = resolved_settings.oidc_session_absolute_timeout_seconds
            session_cookie_value, session_max_age, session_id = session_cookie_from_principal(
                token_response,
                principal,
                resolved_settings,
                max_age_ceiling=(
                    absolute_timeout_seconds if absolute_timeout_seconds > 0 else None
                ),
            )
            session_claims = read_session_cookie(session_cookie_value, resolved_settings)
            session_hash = session_id_hash(session_id, resolved_settings)
            expires_at = datetime.fromtimestamp(session_claims.expires_at, UTC)
            absolute_expires_at = (
                datetime.now(UTC) + timedelta(seconds=absolute_timeout_seconds)
                if absolute_timeout_seconds > 0
                else None
            )
            refresh_token = token_response.get("refresh_token")
            refresh_token_ciphertext = None
            if (
                isinstance(refresh_token, str)
                and refresh_token
                and resolved_settings.oidc_refresh_token_encryption_key
            ):
                refresh_token_ciphertext = encrypt_refresh_token(refresh_token, resolved_settings)
            with session_scope(request.app.state.session_factory) as guard_session:
                guard_repository = AxisPersistenceRepository(guard_session)
                login_block_reason = _fresh_tenant_admission_denial_reason(
                    guard_repository,
                    principal.tenant_id,
                    admission_mode=resolved_settings.tenant_admission_mode,
                )
                if login_block_reason is not None:
                    # Persist the denial in its own committed transaction before
                    # aborting, so the evidence survives the rejected login.
                    guard_repository.append_audit_event(
                        AuditEventCreate(
                            tenant_id=principal.tenant_id,
                            actor_id=principal.actor_id,
                            event_type=tenant_admission_denial_audit_event_type(login_block_reason),
                            payload={
                                "tenant_id": principal.tenant_id,
                                "reason": login_block_reason,
                                "operation": "oidc_login_callback",
                                "session_source": "secure_cookie",
                            },
                        )
                    )
            if login_block_reason is not None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "code": AxisErrorCode.PERMISSION_DENIED.value,
                        "message": "The tenant for this login is not active.",
                        "reason": login_block_reason,
                    },
                )
            # Device metadata is stored on the session row for the owner-facing
            # session inventory; it never enters audit payloads (the client IP
            # in particular stays out of the audit ledger).
            client_metadata = extract_session_client_metadata(request, resolved_settings)
            with session_scope(request.app.state.session_factory) as session:
                repository = AxisPersistenceRepository(session)
                # The session cap is a read-modify-write invariant. Serialize
                # admission for this tenant principal before creating the row so
                # concurrent callbacks cannot each observe only their own
                # uncommitted session and both exceed the configured limit.
                repository.acquire_oidc_session_admission_lock(
                    tenant_id=principal.tenant_id,
                    actor_id=principal.actor_id,
                )
                audit_event = repository.append_audit_event(
                    AuditEventCreate(
                        tenant_id=principal.tenant_id,
                        actor_id=principal.actor_id,
                        event_type="identity.oidc_session.created",
                        payload={
                            "session_id_hash": session_hash,
                            "session_boundary": OIDC_SESSION_BOUNDARY,
                            "expires_at": expires_at.isoformat(),
                            "absolute_expires_at": (
                                absolute_expires_at.isoformat() if absolute_expires_at else None
                            ),
                            "refresh_token_stored": bool(refresh_token_ciphertext),
                            "scopes": principal.scopes,
                        },
                    )
                )
                stored_browser_session = repository.create_oidc_browser_session(
                    OidcBrowserSessionCreate(
                        session_id_hash=session_hash,
                        tenant_id=principal.tenant_id,
                        actor_id=principal.actor_id,
                        scopes=principal.scopes,
                        expires_at=expires_at,
                        absolute_expires_at=absolute_expires_at,
                        refresh_token_ciphertext=refresh_token_ciphertext,
                        user_agent=client_metadata.user_agent,
                        client_ip=client_metadata.client_ip,
                        device_label=client_metadata.device_label,
                        created_audit_event_id=audit_event.id,
                    )
                )
                if resolved_settings.usage_metering_enabled:
                    # Meter the established session on the same durable transaction
                    # that persisted it, so consumption is never at risk of loss.
                    record_tenant_usage_event(
                        repository,
                        principal.tenant_id,
                        TenantUsageMetric.SESSION_CREATED.value,
                        1,
                        source_type="oidc_browser_session",
                        source_id=str(stored_browser_session.id),
                        window_seconds=(
                            resolved_settings.usage_metering_aggregation_window_seconds
                        ),
                        occurred_at=stored_browser_session.created_at,
                    )
                max_concurrent = resolved_settings.oidc_session_max_concurrent
                concurrent_session_quota = repository.get_tenant_quota(
                    principal.tenant_id,
                    TenantQuotaKey.MAX_CONCURRENT_SESSIONS.value,
                )
                if concurrent_session_quota is not None:
                    max_concurrent = concurrent_session_quota.quota_value
                if max_concurrent > 0:
                    active_sessions = repository.list_active_oidc_browser_sessions(
                        tenant_id=principal.tenant_id,
                        actor_id=principal.actor_id,
                    )
                    excess_count = len(active_sessions) - max_concurrent
                    if excess_count > 0:
                        stale_sessions = [
                            active_session
                            for active_session in active_sessions
                            if active_session.session_id_hash != session_hash
                        ][:excess_count]
                        for stale_session in stale_sessions:
                            _expire_stored_session(
                                repository,
                                stale_session,
                                revocation_reason="concurrent_session_limit",
                            )
        except OidcCookieValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": AxisErrorCode.AUTH_REQUIRED.value,
                    "message": "OIDC login state could not be verified.",
                    "reason": exc.reason,
                },
            ) from exc
        except OidcCodeFlowConfigurationError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": AxisErrorCode.AUTH_REQUIRED.value,
                    "message": "OIDC authorization-code login is not configured.",
                    "reason": exc.reason,
                },
            ) from exc
        except (OidcAuthenticationError, OidcTokenExchangeError) as exc:
            reason = getattr(exc, "reason", "token_exchange_failed")
            record_oidc_login_failure(request, reason=reason, principal=principal)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": AxisErrorCode.AUTH_REQUIRED.value,
                    "message": "OIDC authorization-code exchange could not be completed.",
                    "reason": reason,
                },
            ) from exc

        response = RedirectResponse(
            public_redirect(resolved_settings, login_state.return_to),
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )
        set_oidc_session_cookies(
            response,
            session_cookie_value=session_cookie_value,
            session_id=session_id,
            max_age=session_max_age,
        )
        response.delete_cookie(
            resolved_settings.oidc_login_cookie_name,
            path="/identity/oidc",
            secure=resolved_settings.oidc_session_cookie_secure,
            httponly=True,
            samesite="lax",
        )
        return response

    @app.get("/identity/oidc/logout", tags=["system"])
    def oidc_federated_logout(request: Request, return_to: str = "/") -> RedirectResponse:
        try:
            redirect_url = build_end_session_redirect_url(resolved_settings, return_to)
        except OidcCodeFlowConfigurationError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": AxisErrorCode.AUTH_REQUIRED.value,
                    "message": "OIDC federated logout is not configured.",
                    "reason": exc.reason,
                },
            ) from exc

        response = RedirectResponse(
            redirect_url,
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )
        delete_oidc_session_cookie(response)
        revoke_oidc_session_from_cookie(
            request,
            revocation_reason="federated_logout",
            federated_logout=True,
        )
        return response

    @app.post(
        "/identity/session/logout",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["system"],
    )
    def identity_session_logout(request: Request) -> Response:
        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        delete_oidc_session_cookie(response)
        revoke_oidc_session_from_cookie(
            request,
            revocation_reason="user_logout",
            federated_logout=False,
        )
        return response

    @app.post(
        "/identity/session/refresh",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["system"],
    )
    def identity_session_refresh(request: Request) -> Response:
        session_cookie = request.cookies.get(session_cookie_name(resolved_settings))
        if not session_cookie:
            raise _refresh_precondition_error(
                status_code=status.HTTP_401_UNAUTHORIZED,
                reason="missing_session_cookie",
                message="An Axis browser session cookie is required to refresh.",
            )
        try:
            oidc_session = read_session_cookie(session_cookie, resolved_settings)
            session_hash = session_id_hash(oidc_session.session_id, resolved_settings)
        except OidcCodeFlowConfigurationError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": AxisErrorCode.AUTH_REQUIRED.value,
                    "message": "OIDC browser sessions are not configured.",
                    "reason": exc.reason,
                },
            ) from exc
        except OidcCookieValidationError as exc:
            raise _refresh_precondition_error(
                status_code=status.HTTP_401_UNAUTHORIZED,
                reason="invalid_session_cookie",
                message="The OIDC session cookie could not be verified.",
            ) from exc

        # Phase 1: validate preconditions and atomically claim the refresh so
        # concurrent refreshes with the same cookie cannot both proceed. No IdP
        # network I/O happens while this transaction is open.
        claim = _claim_session_refresh(
            request,
            session_hash=session_hash,
            settings=resolved_settings,
        )
        if isinstance(claim, HTTPException):
            raise claim

        # Phase 2: perform the external IdP refresh exchange OUTSIDE any open
        # database transaction, then re-validate the returned principal.
        refresh_failure: tuple[str, str] | None = None
        refresh_rejected_reason: str | None = None
        rotated: _RotatedSessionCookie | None = None
        try:
            token_response = request.app.state.oidc_token_exchanger(
                build_refresh_token_form(
                    settings=resolved_settings,
                    refresh_token=claim.refresh_token,
                ),
                resolved_settings,
            )
            access_token = token_response.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise OidcTokenExchangeError("missing_access_token")
            principal = request.app.state.identity_verifier.verify_authorization_header(
                f"Bearer {access_token}"
            )
            if principal.actor_id != claim.actor_id or principal.tenant_id != claim.tenant_id:
                raise OidcAuthenticationError("refresh_principal_mismatch")
            max_age_ceiling: int | None = None
            if claim.absolute_expires_at is not None:
                max_age_ceiling = int(
                    (
                        ensure_aware_datetime(claim.absolute_expires_at) - datetime.now(UTC)
                    ).total_seconds()
                )
            (
                session_cookie_value,
                session_max_age,
                new_session_id,
            ) = session_cookie_from_principal(
                token_response,
                principal,
                resolved_settings,
                max_age_ceiling=max_age_ceiling,
            )
        except OidcCodeFlowConfigurationError as exc:
            # Configuration faults are not the session's fault; release the
            # claim so the operator can retry after fixing configuration.
            with session_scope(request.app.state.session_factory) as session:
                AxisPersistenceRepository(session).release_oidc_browser_session_refresh(
                    session_hash
                )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": AxisErrorCode.AUTH_REQUIRED.value,
                    "message": "OIDC session refresh is not configured.",
                    "reason": exc.reason,
                },
            ) from exc
        except (OidcAuthenticationError, OidcTokenExchangeError) as exc:
            refresh_failure = (getattr(exc, "reason", "refresh_failed"), "refresh_failed")

        # Phase 3: persist the terminal outcome in a fresh short transaction.
        with session_scope(request.app.state.session_factory) as session:
            repository = AxisPersistenceRepository(session)
            if refresh_failure is not None:
                failure_reason, revocation_reason = refresh_failure
                repository.append_audit_event(
                    AuditEventCreate(
                        tenant_id=claim.tenant_id,
                        actor_id=claim.actor_id,
                        event_type="identity.oidc_session.refresh_failed",
                        payload={
                            "session_id_hash": session_hash,
                            "reason": failure_reason,
                            "session_boundary": OIDC_SESSION_BOUNDARY,
                        },
                    )
                )
                revoke_event = repository.append_audit_event(
                    AuditEventCreate(
                        tenant_id=claim.tenant_id,
                        actor_id=claim.actor_id,
                        event_type="identity.oidc_session.revoked",
                        payload={
                            "session_id_hash": session_hash,
                            "revocation_reason": revocation_reason,
                            "session_boundary": OIDC_SESSION_BOUNDARY,
                            "federated_logout": False,
                        },
                    )
                )
                repository.revoke_oidc_browser_session(
                    OidcBrowserSessionRevocation(
                        session_id_hash=session_hash,
                        revoked_by=OIDC_SESSION_LIFECYCLE_ACTOR,
                        revocation_reason=revocation_reason,
                        revoke_audit_event_id=revoke_event.id,
                    )
                )
            else:
                new_session_hash = session_id_hash(new_session_id, resolved_settings)
                session_claims = read_session_cookie(session_cookie_value, resolved_settings)
                expires_at = datetime.fromtimestamp(session_claims.expires_at, UTC)
                rotated_refresh_token = token_response.get("refresh_token")
                next_refresh_token = (
                    rotated_refresh_token
                    if isinstance(rotated_refresh_token, str) and rotated_refresh_token
                    else claim.refresh_token
                )
                refresh_count = claim.refresh_count + 1
                # Re-capture device metadata from the refreshing request so a
                # rotated session row reflects the device actually holding the
                # cookie now; the metadata stays out of audit payloads.
                client_metadata = extract_session_client_metadata(request, resolved_settings)
                refresh_finalized = repository.finalize_oidc_browser_session_refresh(
                    session_id_hash=session_hash,
                    rotated_to_session_id_hash=new_session_hash,
                )
                if not refresh_finalized:
                    refresh_rejected_reason = "invalid_session_cookie"
                else:
                    audit_event = repository.append_audit_event(
                        AuditEventCreate(
                            tenant_id=principal.tenant_id,
                            actor_id=principal.actor_id,
                            event_type="identity.oidc_session.refreshed",
                            payload={
                                "previous_session_id_hash": session_hash,
                                "session_id_hash": new_session_hash,
                                "session_boundary": OIDC_SESSION_BOUNDARY,
                                "expires_at": expires_at.isoformat(),
                                "absolute_expires_at": (
                                    ensure_aware_datetime(claim.absolute_expires_at).isoformat()
                                    if claim.absolute_expires_at is not None
                                    else None
                                ),
                                "refresh_count": refresh_count,
                                "refresh_token_rotated": bool(
                                    isinstance(rotated_refresh_token, str) and rotated_refresh_token
                                ),
                            },
                        )
                    )
                    repository.create_oidc_browser_session(
                        OidcBrowserSessionCreate(
                            session_id_hash=new_session_hash,
                            tenant_id=principal.tenant_id,
                            actor_id=principal.actor_id,
                            scopes=principal.scopes,
                            expires_at=expires_at,
                            absolute_expires_at=claim.absolute_expires_at,
                            refresh_token_ciphertext=encrypt_refresh_token(
                                next_refresh_token, resolved_settings
                            ),
                            refresh_count=refresh_count,
                            user_agent=client_metadata.user_agent,
                            client_ip=client_metadata.client_ip,
                            device_label=client_metadata.device_label,
                            created_audit_event_id=audit_event.id,
                        )
                    )
                    rotated = _RotatedSessionCookie(
                        session_cookie_value=session_cookie_value,
                        session_id=new_session_id,
                        max_age=session_max_age,
                    )

        if refresh_failure is not None or refresh_rejected_reason is not None or rotated is None:
            failure_reason = (
                refresh_failure[0]
                if refresh_failure
                else refresh_rejected_reason or "refresh_failed"
            )
            failure_response = JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "detail": {
                        "code": AxisErrorCode.AUTH_REQUIRED.value,
                        "message": ("The OIDC session refresh failed and the session was revoked."),
                        "reason": failure_reason,
                    }
                },
            )
            delete_oidc_session_cookie(failure_response)
            return failure_response

        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        set_oidc_session_cookies(
            response,
            session_cookie_value=rotated.session_cookie_value,
            session_id=rotated.session_id,
            max_age=rotated.max_age,
        )
        return response

    def _require_identity_principal(principal: OidcPrincipal | None) -> OidcPrincipal:
        if principal is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": AxisErrorCode.AUTH_REQUIRED.value,
                    "message": "An authenticated OIDC actor is required.",
                    "reason": "missing_authorization",
                },
            )
        return principal

    def _require_session_admin_scope(principal: OidcPrincipal, *, resource: str) -> None:
        try:
            authorize_principal_scopes(
                tenant_id=principal.tenant_id,
                principal=principal,
                required_scopes=[IDENTITY_SESSION_ADMIN_SCOPE],
                attributes={
                    "surface": "identity",
                    "resource": resource,
                },
                message="Managing other actors' sessions requires the admin scope.",
                bind_tenant=False,
            )
        except ScopeAuthorizationError as exc:
            raise _scope_denial_http_exception(exc) from exc

    def _current_session_hash(request: Request) -> str | None:
        session_cookie = request.cookies.get(session_cookie_name(resolved_settings))
        if not session_cookie:
            return None
        try:
            oidc_session = read_session_cookie(session_cookie, resolved_settings)
        except (OidcCodeFlowConfigurationError, OidcCookieValidationError):
            return None
        return session_id_hash(oidc_session.session_id, resolved_settings)

    @app.get(
        "/identity/sessions",
        response_model=IdentityBrowserSessionList,
        responses={
            422: {"description": "Session listing cursor or page size is invalid"},
        },
        tags=["system"],
    )
    def identity_sessions(
        request: Request,
        principal: OidcPrincipalDependency,
        tenant_wide: bool = False,
        page_size: int = Query(default=20, ge=1, le=100),
        cursor: str | None = Query(default=None, min_length=1, max_length=600),
    ) -> IdentityBrowserSessionList:
        resolved_principal = _require_identity_principal(principal)
        if tenant_wide:
            _require_session_admin_scope(resolved_principal, resource="session_listing")
        try:
            cursor_created_at, cursor_row_id = decode_session_cursor(cursor)
        except IdentitySessionCursorError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "The session listing cursor is invalid.",
                    "reason": exc.reason,
                },
            ) from exc
        current_hash = _current_session_hash(request)
        with session_scope(request.app.state.session_factory) as session:
            repository = AxisPersistenceRepository(session)
            stored_sessions = repository.list_oidc_browser_sessions(
                tenant_id=resolved_principal.tenant_id,
                actor_id=None if tenant_wide else resolved_principal.actor_id,
                cursor_created_at=cursor_created_at,
                cursor_row_id=cursor_row_id,
                limit=page_size + 1,
            )
            has_more = len(stored_sessions) > page_size
            page_sessions = stored_sessions[:page_size]
            next_cursor = (
                encode_session_cursor(page_sessions[-1]) if has_more and page_sessions else None
            )
            records = [
                IdentityBrowserSessionRecord(
                    session_ref=str(stored_session.id),
                    actor_id=stored_session.actor_id,
                    status=stored_session.status,
                    current=stored_session.session_id_hash == current_hash,
                    created_at=stored_session.created_at,
                    expires_at=stored_session.expires_at,
                    absolute_expires_at=stored_session.absolute_expires_at,
                    last_seen_at=stored_session.last_seen_at,
                    refresh_count=stored_session.refresh_count,
                    user_agent=stored_session.user_agent,
                    client_ip=stored_session.client_ip,
                    device_label=stored_session.device_label,
                    revoked_at=stored_session.revoked_at,
                    revocation_reason=stored_session.revocation_reason,
                )
                for stored_session in page_sessions
            ]
        return IdentityBrowserSessionList(
            tenant_id=resolved_principal.tenant_id,
            actor_id=resolved_principal.actor_id,
            tenant_wide=tenant_wide,
            sessions=records,
            has_more=has_more,
            next_cursor=next_cursor,
            notes=[
                "Session references are opaque identifiers; no token material is returned.",
                "Revoke a session with POST /identity/sessions/{session_ref}/revoke.",
            ],
        )

    @app.post(
        "/identity/sessions/{session_ref}/revoke",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["system"],
    )
    def identity_session_revoke(
        session_ref: UUID,
        request: Request,
        principal: OidcPrincipalDependency,
    ) -> Response:
        resolved_principal = _require_identity_principal(principal)
        with session_scope(request.app.state.session_factory) as session:
            repository = AxisPersistenceRepository(session)
            stored_session = repository.get_oidc_browser_session_for_update(
                resolved_principal.tenant_id,
                session_ref,
            )
            if stored_session is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "code": AxisErrorCode.NOT_FOUND.value,
                        "message": "The browser session was not found in this tenant.",
                        "reason": "session_not_found",
                    },
                )
            if stored_session.actor_id != resolved_principal.actor_id:
                _require_session_admin_scope(resolved_principal, resource="session_revocation")
                revocation_reason = "admin_revocation"
            else:
                revocation_reason = "self_revocation"
            if stored_session.status in {"active", "refreshing"}:
                _expire_stored_session(
                    repository,
                    stored_session,
                    revocation_reason=revocation_reason,
                    revoked_by=resolved_principal.actor_id,
                )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get(
        "/identity/session",
        response_model=IdentitySessionReadModel,
        tags=["system"],
    )
    def identity_session(
        request: Request,
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> IdentitySessionReadModel:
        # Deliberately resolves instead of raising on missing or invalid
        # credentials: this is the one endpoint an unauthenticated browser must
        # be able to read so the console can render a sign-in gate rather than
        # generic error panels when SSO enforcement is on. The response only
        # ever reports readiness facts and public IdP coordinates (issuer,
        # audience) — never token material, actor or tenant data for a caller
        # whose principal did not verify.
        principal, unauthenticated_reason = _resolve_request_principal(
            request,
            authorization,
        )
        if principal is not None:
            _annotate_request_span_with_principal(principal)
            _record_request_usage_admission(request, principal)
        return build_identity_session_read_model(
            settings=resolved_settings,
            oidc_readiness_report=_oidc_readiness_report(resolved_settings),
            principal=principal,
            unauthenticated_reason=unauthenticated_reason,
        )

    @app.get(
        "/deployment/readiness",
        response_model=DeploymentReadinessReport,
        tags=["system"],
    )
    def deployment_readiness() -> DeploymentReadinessReport:
        return build_deployment_readiness_report(
            resolved_settings,
            oidc_readiness_report=_oidc_readiness_report(resolved_settings),
            object_lock_capability=(
                _audit_export_object_lock_capability(app)
                if _audit_export_worm_settings(resolved_settings)
                else None
            ),
        )

    @app.get(
        "/support/diagnostics",
        response_model=SupportDiagnosticsReport,
        tags=["system"],
    )
    def support_diagnostics() -> SupportDiagnosticsReport:
        oidc_report = _oidc_readiness_report(resolved_settings)
        deployment_report = build_deployment_readiness_report(
            resolved_settings,
            oidc_readiness_report=oidc_report,
            object_lock_capability=(
                _audit_export_object_lock_capability(app)
                if _audit_export_worm_settings(resolved_settings)
                else None
            ),
        )
        return build_support_diagnostics_report(
            resolved_settings,
            oidc_readiness_report=oidc_report,
            deployment_readiness_report=deployment_report,
        )

    @operations_router.get(
        "/overview",
        response_model=ManufacturingOverview,
        responses={
            404: {"description": "Manufacturing overview reference record not found"},
            422: {"description": "Manufacturing overview reference payload invalid"},
        },
        tags=["demo"],
    )
    def manufacturing_overview(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(min_length=1),
    ) -> ManufacturingOverview:
        _authorize_tenant_read(tenant_id, principal)
        try:
            return get_persisted_manufacturing_overview(repository, tenant_id=tenant_id)
        except DemoReferenceRecordNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "Manufacturing overview reference record not found.",
                    "tenant_id": tenant_id,
                    "surface": "overview",
                },
            ) from exc
        except DemoReferenceRecordInvalid as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "Manufacturing overview reference payload is invalid.",
                    "tenant_id": tenant_id,
                    "surface": "overview",
                },
            ) from exc

    # Bootstrap seeds demonstration data, so it has no production operations alias.
    @app.post(
        "/demo/manufacturing/bootstrap",
        response_model=DemoBootstrapRecordView,
        responses={
            403: {"description": "Demo scenario bootstrap permission denied"},
            422: {"description": "Demo scenario bootstrap validation failed"},
        },
        deprecated=True,
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    def manufacturing_demo_bootstrap(
        bootstrap_request: DemoBootstrapRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        response: Response,
    ) -> DemoBootstrapRecordView:
        bound_request = _bind_connector_run_actor(
            bootstrap_request,
            principal,
            actor_field="requested_by",
        )
        try:
            result = bootstrap_demo_scenario(repository, bound_request)
        except DemoBootstrapPermissionDenied as exc:
            reason = (
                "missing_required_scope"
                if exc.decision.reason.startswith("missing_scope:")
                else exc.decision.reason
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot bootstrap the demo scenario.",
                    "required_permission": exc.required_permission,
                    "reason": reason,
                    "permission_reason": exc.decision.reason,
                },
            ) from exc
        except DemoBootstrapValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

        if result.idempotent_replay:
            response.status_code = status.HTTP_200_OK
        return result

    @operations_router.get(
        "/workflows",
        response_model=ManufacturingWorkflowConsole,
        responses={
            404: {"description": "Workflow console reference record not found"},
            422: {"description": "Workflow console reference payload invalid"},
        },
        tags=["demo"],
    )
    def manufacturing_workflow_console(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(min_length=1),
    ) -> ManufacturingWorkflowConsole:
        _authorize_tenant_read(tenant_id, principal)
        try:
            return get_persisted_manufacturing_workflow_console(
                repository,
                tenant_id=tenant_id,
            )
        except WorkflowReferenceRecordNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "Manufacturing workflow console reference record not found.",
                    "tenant_id": tenant_id,
                    "surface": "workflows",
                },
            ) from exc
        except WorkflowReferenceRecordInvalid as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "Manufacturing workflow console reference payload is invalid.",
                    "tenant_id": tenant_id,
                    "surface": "workflows",
                },
            ) from exc

    @operations_router.get(
        "/workflows/runs",
        response_model=ManufacturingWorkflowConsole,
        tags=["demo"],
    )
    def manufacturing_persisted_workflow_runs(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(min_length=1),
        state: str | None = Query(default=None, min_length=1),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> ManufacturingWorkflowConsole:
        _authorize_tenant_read(tenant_id, principal)
        return query_persisted_workflow_runs(
            repository,
            WorkflowRunQuery(tenant_id=tenant_id, state=state, limit=limit),
        )

    @operations_router.get(
        "/simulation/replay",
        response_model=ManufacturingReplaySimulation,
        responses={
            403: {"description": "Replay policy-set comparison denied or disabled"},
            422: {"description": "Replay policy-set comparison validation failed"},
        },
        tags=["demo"],
    )
    def manufacturing_replay_simulation(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        workflow_id: str | None = Query(default=None, min_length=1),
        limit: int = Query(default=20, ge=1, le=100),
        retention_days: int = Query(default=365, ge=1, le=3650),
        legal_hold: bool = Query(default=False),
        baseline_policy_set_id: str | None = Query(default=None, min_length=1, max_length=180),
        candidate_policy_set_id: str | None = Query(default=None, min_length=1, max_length=180),
        connector_id: str | None = Query(default=None, min_length=1, max_length=160),
    ) -> ManufacturingReplaySimulation:
        _authorize_tenant_read(tenant_id, principal)
        if any(
            value is not None
            for value in (baseline_policy_set_id, candidate_policy_set_id, connector_id)
        ):
            _authorize_tenant_read(tenant_id, principal)
        try:
            return build_replay_simulation(
                repository,
                ReplaySimulationQuery(
                    tenant_id=tenant_id,
                    workflow_id=workflow_id,
                    limit=limit,
                    retention_days=retention_days,
                    legal_hold=legal_hold,
                    baseline_policy_set_id=baseline_policy_set_id,
                    candidate_policy_set_id=candidate_policy_set_id,
                    connector_id=connector_id,
                ),
                arbitrary_policy_set_diff_enabled=(
                    resolved_settings.replay_arbitrary_policy_set_diff_enabled
                ),
            )
        except ReplayPolicySetDiffDisabled as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": ("Arbitrary policy-set comparison over replay windows is disabled."),
                    "reason": exc.reason,
                },
            ) from exc
        except ReplayPolicySetDiffValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.post(
        "/simulation/replay/outputs",
        response_model=ReplaySimulationOutputRecord,
        responses={
            403: {"description": "Replay simulation output permission denied"},
            409: {"description": "Replay simulation output already exists or conflicts"},
            422: {"description": "Replay simulation output validation failed"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    def manufacturing_replay_simulation_output_create(
        replay_output_request: ReplaySimulationOutputPersistRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        response: Response,
    ) -> ReplaySimulationOutputRecord:
        try:
            bound_request = _bind_demo_requested_by(replay_output_request, principal)
            result = persist_replay_simulation_output(
                repository,
                bound_request,
                arbitrary_policy_set_diff_enabled=(
                    resolved_settings.replay_arbitrary_policy_set_diff_enabled
                ),
            )
        except ReplayPolicySetDiffDisabled as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": ("Arbitrary policy-set comparison over replay windows is disabled."),
                    "reason": exc.reason,
                },
            ) from exc
        except ReplayPolicySetDiffValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc
        except ReplaySimulationOutputPermissionDenied as exc:
            reason = (
                "missing_required_scope"
                if exc.decision.reason.startswith("missing_scope:")
                else exc.decision.reason
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot persist replay simulation outputs.",
                    "required_permission": exc.required_permission,
                    "reason": reason,
                    "permission_reason": exc.decision.reason,
                },
            ) from exc
        except ReplaySimulationOutputConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.POLICY_VIOLATION.value,
                    "message": "The replay simulation output conflicts with existing state.",
                    "reason": exc.reason,
                    "simulation_output_id": exc.simulation_output_id,
                },
            ) from exc
        except ReplaySimulationOutputValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

        if result.idempotent_replay:
            response.status_code = status.HTTP_200_OK
        return result

    @operations_router.get(
        "/operations",
        response_model=ManufacturingOperationsDataset,
        tags=["demo"],
    )
    def manufacturing_operations_dataset(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        domain: str | None = Query(default=None, min_length=1),
        status: str | None = Query(default=None, min_length=1),
        record_type: str | None = Query(default=None, min_length=1),
        source_system: str | None = Query(default=None, min_length=1),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> ManufacturingOperationsDataset:
        _authorize_tenant_read(tenant_id, principal)
        return query_manufacturing_operations_dataset(
            repository,
            ManufacturingOperationQuery(
                tenant_id=tenant_id,
                domain=domain,
                status=status,
                record_type=record_type,
                source_system=source_system,
                limit=limit,
            ),
        )

    @operations_router.get(
        "/operations/snapshot",
        response_model=ManufacturingOperationsSnapshot,
        tags=["demo"],
    )
    def manufacturing_operations_snapshot(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        operation_limit: int = Query(default=100, ge=1, le=200),
        workflow_limit: int = Query(default=25, ge=1, le=100),
        approval_limit: int = Query(default=25, ge=1, le=100),
        artifact_limit: int = Query(default=10, ge=1, le=50),
        audit_limit: int = Query(default=25, ge=1, le=100),
    ) -> ManufacturingOperationsSnapshot:
        _authorize_tenant_read(tenant_id, principal)
        return build_manufacturing_operations_snapshot(
            repository,
            ManufacturingOperationsSnapshotQuery(
                tenant_id=tenant_id,
                operation_limit=operation_limit,
                workflow_limit=workflow_limit,
                approval_limit=approval_limit,
                artifact_limit=artifact_limit,
                audit_limit=audit_limit,
            ),
        )

    @operations_router.get(
        "/notifications",
        response_model=ManufacturingNotificationCenter,
        tags=["demo"],
    )
    def manufacturing_notifications(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        operation_limit: int = Query(default=100, ge=1, le=200),
        workflow_limit: int = Query(default=25, ge=1, le=100),
        approval_limit: int = Query(default=25, ge=1, le=100),
        artifact_limit: int = Query(default=10, ge=1, le=50),
        audit_limit: int = Query(default=25, ge=1, le=100),
        notification_limit: int = Query(default=8, ge=1, le=25),
        actor_id: str | None = Query(default=None, min_length=1),
    ) -> ManufacturingNotificationCenter:
        if principal is not None:
            if principal.tenant_id != tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "code": AxisErrorCode.PERMISSION_DENIED.value,
                        "message": "The authenticated OIDC tenant cannot access this tenant scope.",
                        "reason": "tenant_mismatch",
                    },
                )
            if actor_id is not None and actor_id != principal.actor_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "code": AxisErrorCode.PERMISSION_DENIED.value,
                        "message": (
                            "The requested notification actor does not match the OIDC actor."
                        ),
                        "reason": "actor_mismatch",
                    },
                )
            actor_id = principal.actor_id

        return build_manufacturing_notification_center(
            repository,
            ManufacturingNotificationQuery(
                tenant_id=tenant_id,
                operation_limit=operation_limit,
                workflow_limit=workflow_limit,
                approval_limit=approval_limit,
                artifact_limit=artifact_limit,
                audit_limit=audit_limit,
                notification_limit=notification_limit,
                actor_id=actor_id,
            ),
        )

    @operations_router.post(
        "/notifications/{notification_id}/acknowledgement",
        response_model=ManufacturingNotificationAcknowledgementResult,
        responses={
            403: {"description": "Notification acknowledgement permission denied"},
            404: {"description": "Notification not found"},
            409: {"description": "Notification acknowledgement state conflict"},
        },
        tags=["demo"],
    )
    def manufacturing_notification_acknowledgement(
        notification_id: str,
        acknowledgement_request: ManufacturingNotificationAcknowledgementRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> ManufacturingNotificationAcknowledgementResult:
        bound_request = _bind_demo_actor(acknowledgement_request, principal)
        try:
            return record_manufacturing_notification_acknowledgement(
                repository,
                notification_id,
                bound_request,
            )
        except ManufacturingNotificationAcknowledgementPermissionDenied as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot acknowledge this notification.",
                    "required_permissions": ["notifications:acknowledge"],
                    "reason": exc.decision.reason,
                },
            ) from exc
        except ManufacturingNotificationNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": (
                        "The notification is not present in the current tenant notification window."
                    ),
                    "notification_id": exc.notification_id,
                },
            ) from exc
        except ManufacturingNotificationAcknowledgementConflict as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": AxisErrorCode.CONFLICT.value,
                    "message": ("The notification acknowledgement conflicts with persisted state."),
                    "reason": exc.reason,
                    "notification_id": exc.notification_id,
                    "current_state": exc.current_state,
                    "requested_state": exc.requested_state,
                },
            ) from exc

    @operations_router.get(
        "/demo-readiness",
        response_model=ManufacturingDemoReadinessReport,
        tags=["demo"],
    )
    def manufacturing_demo_readiness(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        operation_limit: int = Query(default=100, ge=1, le=200),
        workflow_limit: int = Query(default=25, ge=1, le=100),
        approval_limit: int = Query(default=25, ge=1, le=100),
        artifact_limit: int = Query(default=10, ge=1, le=50),
        audit_limit: int = Query(default=25, ge=1, le=100),
    ) -> ManufacturingDemoReadinessReport:
        _authorize_tenant_read(tenant_id, principal)
        return build_manufacturing_demo_readiness_report(
            repository,
            ManufacturingOperationsSnapshotQuery(
                tenant_id=tenant_id,
                operation_limit=operation_limit,
                workflow_limit=workflow_limit,
                approval_limit=approval_limit,
                artifact_limit=artifact_limit,
                audit_limit=audit_limit,
            ),
        )

    @operations_router.post(
        "/operations/daily-brief",
        response_model=DailyPlantBriefRecord,
        responses={
            403: {"description": "Daily plant brief permission denied"},
            409: {"description": "Daily plant brief idempotency conflict"},
            422: {"description": "Daily plant brief validation failed"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    def manufacturing_daily_plant_brief(
        brief_request: DailyPlantBriefRequest,
        repository: PersistenceRepository,
        response: Response,
        principal: OidcPrincipalDependency,
    ) -> DailyPlantBriefRecord:
        bound_request = _bind_demo_requested_by(brief_request, principal)
        try:
            result = generate_daily_plant_brief(repository, bound_request)
        except DailyPlantBriefPermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot generate a daily plant brief.",
                    "required_permissions": [
                        "briefs:generate",
                        "audit:read",
                        "workflows:read",
                    ],
                    "reason": exc.decision.reason,
                },
            ) from exc
        except DailyPlantBriefIdempotencyConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.POLICY_VIOLATION.value,
                    "message": "The daily plant brief idempotency key conflicts.",
                    "brief_id": exc.brief_id,
                },
            ) from exc
        except DailyPlantBriefValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

        if result.idempotent_replay:
            response.status_code = status.HTTP_200_OK
        return result

    @operations_router.post(
        "/operations/risk-scenarios/quality",
        response_model=QualityRiskScenarioRecord,
        responses={
            403: {"description": "Quality risk scenario permission denied"},
            409: {"description": "Quality risk scenario idempotency conflict"},
            422: {"description": "Quality risk scenario validation failed"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    def manufacturing_quality_risk_scenario(
        scenario_request: QualityRiskScenarioRequest,
        repository: PersistenceRepository,
        response: Response,
        principal: OidcPrincipalDependency,
    ) -> QualityRiskScenarioRecord:
        bound_request = _bind_demo_requested_by(scenario_request, principal)
        try:
            result = generate_quality_risk_scenario(repository, bound_request)
        except QualityRiskScenarioPermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot generate a quality risk scenario.",
                    "required_permissions": [
                        "quality:read",
                        "workflows:read",
                        "audit:read",
                    ],
                    "reason": exc.decision.reason,
                },
            ) from exc
        except QualityRiskScenarioIdempotencyConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.POLICY_VIOLATION.value,
                    "message": "The quality risk scenario idempotency key conflicts.",
                    "scenario_id": exc.scenario_id,
                },
            ) from exc
        except QualityRiskScenarioValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

        if result.idempotent_replay:
            response.status_code = status.HTTP_200_OK
        return result

    @operations_router.post(
        "/operations/risk-scenarios/maintenance",
        response_model=MaintenanceRiskScenarioRecord,
        responses={
            403: {"description": "Maintenance risk scenario permission denied"},
            409: {"description": "Maintenance risk scenario idempotency conflict"},
            422: {"description": "Maintenance risk scenario validation failed"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    def manufacturing_maintenance_risk_scenario(
        scenario_request: MaintenanceRiskScenarioRequest,
        repository: PersistenceRepository,
        response: Response,
        principal: OidcPrincipalDependency,
    ) -> MaintenanceRiskScenarioRecord:
        bound_request = _bind_demo_requested_by(scenario_request, principal)
        try:
            result = generate_maintenance_risk_scenario(repository, bound_request)
        except MaintenanceRiskScenarioPermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot generate a maintenance risk scenario.",
                    "required_permissions": [
                        "maintenance:read",
                        "workflows:read",
                        "audit:read",
                    ],
                    "reason": exc.decision.reason,
                },
            ) from exc
        except MaintenanceRiskScenarioIdempotencyConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.POLICY_VIOLATION.value,
                    "message": ("The maintenance risk scenario idempotency key conflicts."),
                    "scenario_id": exc.scenario_id,
                },
            ) from exc
        except MaintenanceRiskScenarioValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

        if result.idempotent_replay:
            response.status_code = status.HTTP_200_OK
        return result

    @operations_router.post(
        "/operations/risk-scenarios/supplier-delay",
        response_model=SupplierDelayScenarioRecord,
        responses={
            403: {"description": "Supplier delay scenario permission denied"},
            409: {"description": "Supplier delay scenario idempotency conflict"},
            422: {"description": "Supplier delay scenario validation failed"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    def manufacturing_supplier_delay_scenario(
        scenario_request: SupplierDelayScenarioRequest,
        repository: PersistenceRepository,
        response: Response,
        principal: OidcPrincipalDependency,
    ) -> SupplierDelayScenarioRecord:
        bound_request = _bind_demo_requested_by(scenario_request, principal)
        try:
            result = generate_supplier_delay_scenario(repository, bound_request)
        except SupplierDelayScenarioPermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot generate a supplier delay scenario.",
                    "required_permissions": [
                        "supply:read",
                        "workflows:read",
                        "audit:read",
                    ],
                    "reason": exc.decision.reason,
                },
            ) from exc
        except SupplierDelayScenarioIdempotencyConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.POLICY_VIOLATION.value,
                    "message": "The supplier delay scenario idempotency key conflicts.",
                    "scenario_id": exc.scenario_id,
                },
            ) from exc
        except SupplierDelayScenarioValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

        if result.idempotent_replay:
            response.status_code = status.HTTP_200_OK
        return result

    @operations_router.get(
        "/agents",
        response_model=ManufacturingAgentRegistry,
        responses={
            404: {"description": "Agent registry reference record not found"},
            422: {"description": "Agent registry reference payload invalid"},
        },
        tags=["demo"],
    )
    def manufacturing_agent_registry(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(min_length=1),
    ) -> ManufacturingAgentRegistry:
        _authorize_tenant_read(tenant_id, principal)
        try:
            return get_persisted_manufacturing_agent_registry(
                repository,
                tenant_id=tenant_id,
            )
        except AgentReferenceRecordNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "Manufacturing agent registry reference record not found.",
                    "tenant_id": tenant_id,
                    "surface": "agents",
                },
            ) from exc
        except AgentReferenceRecordInvalid as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "Manufacturing agent registry reference payload is invalid.",
                    "tenant_id": tenant_id,
                    "surface": "agents",
                },
            ) from exc

    @operations_router.post(
        "/agents/{agent_id}/runs",
        response_model=AgentRunResult,
        responses={
            403: {"description": "Agent run permission denied or platform policy denied"},
            404: {"description": "Agent or agent registry reference record not found"},
            409: {"description": "Agent run idempotency conflict"},
            422: {
                "description": (
                    "Agent is not executable or the registry reference payload is invalid"
                )
            },
        },
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    async def manufacturing_agent_run(
        agent_id: str,
        run_request: AgentRunStartRequest,
        repository: PersistenceRepository,
        model_runtime: ModelInvocationRuntimeDependency,
        workflow_runtime: WorkflowRuntime,
        principal: OidcPrincipalDependency,
        response: Response,
    ) -> AgentRunResult:
        with telemetry.tracer.start_as_current_span("axis.agent_run.start") as span:
            set_span_attributes(
                span,
                {
                    ATTR_TENANT_ID: principal.tenant_id if principal else None,
                    ATTR_ACTOR_ID: principal.actor_id if principal else None,
                },
            )
            try:
                bound_run_request = _bind_demo_tenant_actor(run_request, principal)
                result = await start_agent_run(
                    repository,
                    agent_id,
                    bound_run_request,
                    model_runtime,
                    execution_enabled=resolved_settings.agent_run_execution_enabled,
                    max_model_calls=resolved_settings.agent_run_max_model_calls,
                    external_model_egress_enabled=(resolved_settings.external_model_egress_enabled),
                    model_prompt_excerpt_chars=(
                        resolved_settings.model_invocation_prompt_excerpt_chars
                    ),
                    usage_metering_enabled=resolved_settings.usage_metering_enabled,
                    usage_window_seconds=(
                        resolved_settings.usage_metering_aggregation_window_seconds
                    ),
                    workflow_runtime=workflow_runtime,
                )
            except AgentReferenceRecordNotFound as exc:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": AxisErrorCode.NOT_FOUND.value,
                        "message": "Manufacturing agent registry reference record not found.",
                        "surface": "agents",
                    },
                ) from exc
            except AgentReferenceRecordInvalid as exc:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": AxisErrorCode.VALIDATION_FAILED.value,
                        "message": "Manufacturing agent registry reference payload is invalid.",
                        "surface": "agents",
                    },
                ) from exc
            except AgentRunAgentNotFound as exc:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": AxisErrorCode.NOT_FOUND.value,
                        "message": "The agent was not found in the persisted registry.",
                        "reason": "agent_not_found",
                        "agent_id": agent_id,
                    },
                ) from exc
            except AgentRunAgentNotExecutable as exc:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": AxisErrorCode.VALIDATION_FAILED.value,
                        "message": exc.message,
                        "reason": exc.reason,
                        "agent_id": agent_id,
                    },
                ) from exc
            except AgentRunPermissionDenied as exc:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": AxisErrorCode.PERMISSION_DENIED.value,
                        "message": "The actor cannot execute runs for this agent.",
                        "required_permissions": exc.required_permissions,
                        "reason": exc.decision.reason,
                    },
                ) from exc
            except PlatformPolicyEnforcementDenied as exc:
                repository.session.commit()
                raise HTTPException(
                    status_code=403,
                    detail=_platform_policy_denied_detail(
                        exc,
                        "A platform policy denies this agent run.",
                    ),
                ) from exc
            except AgentRunIdempotencyConflict as exc:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": AxisErrorCode.CONFLICT.value,
                        "message": ("The idempotency key already exists with a different payload."),
                        "reason": "idempotency_key_conflict",
                        "run_id": str(exc.run_id),
                    },
                ) from exc

            outcome = "idempotent_replay" if result.idempotent_replay else result.status
            set_span_attributes(span, {ATTR_OUTCOME: outcome})
            if result.idempotent_replay:
                response.status_code = status.HTTP_200_OK
            return result

    @operations_router.get(
        "/agents/{agent_id}/runs",
        response_model=AgentRunList,
        responses={
            403: {"description": "Agent run read permission denied"},
            422: {"description": "Agent run listing cursor is invalid"},
        },
        tags=["demo"],
    )
    def manufacturing_agent_run_list(
        agent_id: str,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        page_size: int = Query(default=20, ge=1, le=100),
        cursor: str | None = Query(default=None, min_length=1, max_length=600),
    ) -> AgentRunList:
        _authorize_tenant_read(tenant_id, principal)
        try:
            cursor_created_at, cursor_row_id = decode_agent_run_cursor(cursor)
        except AgentRunCursorError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "The agent run listing cursor is invalid.",
                    "reason": exc.reason,
                },
            ) from exc
        results = list_agent_run_results(
            repository,
            tenant_id,
            agent_id,
            cursor_created_at=cursor_created_at,
            cursor_row_id=cursor_row_id,
            limit=page_size + 1,
        )
        has_more = len(results) > page_size
        page_results = results[:page_size]
        next_cursor = (
            encode_agent_run_cursor(page_results[-1]) if has_more and page_results else None
        )
        return AgentRunList(
            tenant_id=tenant_id,
            agent_id=agent_id,
            runs=page_results,
            has_more=has_more,
            next_cursor=next_cursor,
            run_notes=[
                "Runs are listed newest-first with keyset continuation.",
                "Context evidence is reference-based; prompts and model outputs "
                "are never persisted on the run.",
            ],
        )

    @operations_router.get(
        "/agents/{agent_id}/runs/{run_id}",
        response_model=AgentRunResult,
        responses={
            403: {"description": "Agent run read permission denied"},
            404: {"description": "Agent run not found"},
        },
        tags=["demo"],
    )
    def manufacturing_agent_run_detail(
        agent_id: str,
        run_id: str,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
    ) -> AgentRunResult:
        _authorize_tenant_read(tenant_id, principal)
        try:
            return get_agent_run_result(repository, tenant_id, agent_id, run_id)
        except AgentRunNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "The agent run was not found.",
                    "reason": "agent_run_not_found",
                },
            ) from exc

    @operations_router.get(
        "/actions",
        response_model=ManufacturingActionRegistry,
        responses={
            404: {"description": "Action registry reference record not found"},
            422: {"description": "Action registry reference payload invalid"},
        },
        tags=["demo"],
    )
    def manufacturing_action_registry(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(min_length=1),
    ) -> ManufacturingActionRegistry:
        _authorize_tenant_read(tenant_id, principal)
        try:
            return get_persisted_manufacturing_action_registry(
                repository,
                tenant_id=tenant_id,
            )
        except ActionReferenceRecordNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "Manufacturing action registry reference record not found.",
                    "tenant_id": tenant_id,
                    "surface": "actions",
                },
            ) from exc
        except ActionReferenceRecordInvalid as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "Manufacturing action registry reference payload is invalid.",
                    "tenant_id": tenant_id,
                    "surface": "actions",
                },
            ) from exc

    @operations_router.get(
        "/connectors",
        response_model=ManufacturingConnectorRegistry,
        responses={
            404: {"description": "Connector registry reference record not found"},
            422: {"description": "Connector registry reference payload invalid"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_registry(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(min_length=1),
    ) -> ManufacturingConnectorRegistry:
        _authorize_tenant_read(tenant_id, principal)
        try:
            return get_persisted_manufacturing_connector_registry(
                repository,
                tenant_id=tenant_id,
            )
        except ConnectorReferenceRecordNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "Manufacturing connector registry reference record not found.",
                    "tenant_id": tenant_id,
                    "surface": "connectors",
                },
            ) from exc
        except ConnectorReferenceRecordInvalid as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "Manufacturing connector registry reference payload is invalid.",
                    "tenant_id": tenant_id,
                    "surface": "connectors",
                },
            ) from exc

    @data_router.get(
        "/assets",
        response_model=DataAssetCatalog,
        responses={
            403: {"description": "Tenant scope read permission denied"},
            404: {"description": "Tenant not found"},
        },
    )
    def tenant_data_asset_catalog(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(min_length=1),
    ) -> DataAssetCatalog:
        _authorize_tenant_read(tenant_id, principal)
        stewardship_by_asset = {
            record.asset_id: stewardship_summary_for_asset(record)
            for record in repository.list_all_current_data_asset_stewardship(tenant_id)
        }
        return build_data_asset_catalog(
            get_persisted_manufacturing_connector_registry(
                repository,
                tenant_id=tenant_id,
            ),
            stewardship_by_asset=stewardship_by_asset,
            observed_resource_counts=repository.count_data_resource_observations_by_asset(
                tenant_id
            ),
        )

    def _data_asset_not_found(tenant_id: str, asset_id: str) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": AxisErrorCode.NOT_FOUND.value,
                "message": "Data asset is not part of this tenant catalog.",
                "tenant_id": tenant_id,
                "surface": "data",
                "asset_id": asset_id,
            },
        )

    @data_router.get(
        "/assets/{asset_id}/stewardship",
        response_model=DataAssetStewardshipView,
        responses={
            403: {"description": "Tenant scope read permission denied"},
            404: {"description": "Tenant or data asset not found"},
        },
    )
    def data_asset_stewardship_view_route(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(min_length=1),
        asset_id: str = Path(min_length=1),
    ) -> DataAssetStewardshipView:
        _authorize_tenant_read(tenant_id, principal)
        try:
            ensure_data_asset_in_catalog(repository, tenant_id=tenant_id, asset_id=asset_id)
        except DataAssetNotInCatalog as exc:
            raise _data_asset_not_found(tenant_id, asset_id) from exc
        return get_data_asset_stewardship_view(
            repository,
            tenant_id=tenant_id,
            asset_id=asset_id,
        )

    @data_router.put(
        "/assets/{asset_id}/stewardship",
        response_model=DataAssetStewardshipView,
        responses={
            403: {"description": "Tenant scope write permission denied"},
            404: {"description": "Tenant or data asset not found"},
            409: {"description": "Stewardship revision or idempotency conflict"},
        },
    )
    def declare_data_asset_stewardship_route(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        request_model: DataAssetStewardshipDeclarationRequest,
        tenant_id: str = Query(min_length=1),
        asset_id: str = Path(min_length=1),
    ) -> JSONResponse:
        _authorize_tenant_read(tenant_id, principal)
        try:
            ensure_data_asset_in_catalog(repository, tenant_id=tenant_id, asset_id=asset_id)
        except DataAssetNotInCatalog as exc:
            raise _data_asset_not_found(tenant_id, asset_id) from exc
        try:
            record_view, outcome = declare_data_asset_stewardship(
                repository,
                tenant_id=tenant_id,
                asset_id=asset_id,
                request=request_model,
                principal_actor_id=principal.actor_id if principal is not None else None,
            )
        except DataAssetStewardshipConflict as exc:
            detail = {
                "code": AxisErrorCode.CONFLICT.value,
                "message": "The stewardship declaration conflicts with persisted state.",
                "reason": exc.reason,
                "asset_id": exc.asset_id,
            }
            if exc.current_revision_number is not None:
                detail["current_revision"] = exc.current_revision_number
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail) from exc
        view = DataAssetStewardshipView(
            tenant_id=tenant_id,
            asset_id=asset_id,
            stewardship=record_view,
        )
        return JSONResponse(
            status_code=(status.HTTP_201_CREATED if outcome == "created" else status.HTTP_200_OK),
            content=view.model_dump(mode="json"),
        )

    @data_router.get(
        "/assets/{asset_id}/resources",
        response_model=DataAssetResourcesView,
        responses={
            403: {"description": "Tenant scope read permission denied"},
            404: {"description": "Tenant or data asset not found"},
        },
    )
    def data_asset_resources_route(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(min_length=1),
        asset_id: str = Path(min_length=1),
    ) -> DataAssetResourcesView:
        _authorize_tenant_read(tenant_id, principal)
        try:
            ensure_data_asset_in_catalog(repository, tenant_id=tenant_id, asset_id=asset_id)
        except DataAssetNotInCatalog as exc:
            raise _data_asset_not_found(tenant_id, asset_id) from exc
        return list_data_asset_resources(
            repository,
            tenant_id=tenant_id,
            asset_id=asset_id,
        )

    @data_router.get(
        "/assets/{asset_id}/contract",
        response_model=DataAssetContractView,
        responses={
            403: {"description": "Tenant scope read permission denied"},
            404: {"description": "Tenant or data asset not found"},
        },
    )
    def data_asset_contract_view_route(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(min_length=1),
        asset_id: str = Path(min_length=1),
    ) -> DataAssetContractView:
        _authorize_tenant_read(tenant_id, principal)
        try:
            ensure_data_asset_in_catalog(repository, tenant_id=tenant_id, asset_id=asset_id)
        except DataAssetNotInCatalog as exc:
            raise _data_asset_not_found(tenant_id, asset_id) from exc
        return get_data_asset_contract_view(
            repository,
            tenant_id=tenant_id,
            asset_id=asset_id,
        )

    @data_router.put(
        "/assets/{asset_id}/contract",
        response_model=DataAssetContractView,
        responses={
            403: {"description": "Tenant scope write permission denied"},
            404: {"description": "Tenant or data asset not found"},
            409: {"description": "Contract revision or idempotency conflict"},
        },
    )
    def declare_data_asset_contract_route(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        request_model: DataAssetContractDeclarationRequest,
        tenant_id: str = Query(min_length=1),
        asset_id: str = Path(min_length=1),
    ) -> JSONResponse:
        _authorize_tenant_read(tenant_id, principal)
        try:
            ensure_data_asset_in_catalog(repository, tenant_id=tenant_id, asset_id=asset_id)
        except DataAssetNotInCatalog as exc:
            raise _data_asset_not_found(tenant_id, asset_id) from exc
        try:
            contract_view, outcome = declare_data_asset_contract(
                repository,
                tenant_id=tenant_id,
                asset_id=asset_id,
                request=request_model,
                principal_actor_id=principal.actor_id if principal is not None else None,
            )
        except DataAssetContractConflict as exc:
            detail = {
                "code": AxisErrorCode.CONFLICT.value,
                "message": "The data contract declaration conflicts with persisted state.",
                "reason": exc.reason,
                "asset_id": exc.asset_id,
            }
            if exc.current_revision_number is not None:
                detail["current_revision"] = exc.current_revision_number
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail) from exc
        view = DataAssetContractView(
            tenant_id=tenant_id,
            asset_id=asset_id,
            contract=contract_view,
        )
        return JSONResponse(
            status_code=(status.HTTP_201_CREATED if outcome == "created" else status.HTTP_200_OK),
            content=view.model_dump(mode="json"),
        )

    @data_router.get(
        "/assets/{asset_id}/contract/evaluation",
        response_model=DataAssetContractEvaluationView,
        responses={
            403: {"description": "Tenant scope read permission denied"},
            404: {"description": "Tenant or data asset not found"},
        },
    )
    def data_asset_contract_evaluation_route(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(min_length=1),
        asset_id: str = Path(min_length=1),
    ) -> DataAssetContractEvaluationView:
        _authorize_tenant_read(tenant_id, principal)
        try:
            ensure_data_asset_in_catalog(repository, tenant_id=tenant_id, asset_id=asset_id)
        except DataAssetNotInCatalog as exc:
            raise _data_asset_not_found(tenant_id, asset_id) from exc
        return evaluate_data_asset_contract(
            repository,
            tenant_id=tenant_id,
            asset_id=asset_id,
        )

    @data_router.get(
        "/assets/{asset_id}/lineage",
        response_model=DataAssetLineageView,
        responses={
            403: {"description": "Tenant scope read permission denied"},
            404: {"description": "Tenant or data asset not found"},
        },
    )
    def data_asset_lineage_view_route(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(min_length=1),
        asset_id: str = Path(min_length=1),
    ) -> DataAssetLineageView:
        _authorize_tenant_read(tenant_id, principal)
        try:
            ensure_data_asset_in_catalog(repository, tenant_id=tenant_id, asset_id=asset_id)
        except DataAssetNotInCatalog as exc:
            raise _data_asset_not_found(tenant_id, asset_id) from exc
        return build_data_asset_lineage_view(
            repository,
            tenant_id=tenant_id,
            asset_id=asset_id,
        )

    @operations_router.get(
        "/connectors/manifests",
        response_model=ManufacturingConnectorManifestRegistry,
        responses={403: {"description": "Connector manifest read permission denied"}},
        tags=["demo"],
    )
    def manufacturing_connector_manifests(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        connector_id: str | None = Query(default=None, min_length=1),
        status: str | None = Query(default=None, min_length=1),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> ManufacturingConnectorManifestRegistry:
        _authorize_tenant_read(tenant_id, principal)
        return build_connector_manifest_registry(
            repository,
            ConnectorManifestQuery(
                tenant_id=tenant_id,
                connector_id=connector_id,
                status=status,
                limit=limit,
            ),
        )

    @operations_router.post(
        "/connectors/manifests",
        response_model=ConnectorManifestRecordView,
        responses={
            403: {"description": "Connector manifest actor binding permission denied"},
            409: {"description": "Connector manifest already exists"},
            422: {"description": "Connector manifest validation failed"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    def manufacturing_connector_manifest_create(
        manifest: ConnectorManifestCreateRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> ConnectorManifestRecordView:
        bound_manifest = _bind_connector_run_actor(
            manifest,
            principal,
            actor_field="registered_by",
        )
        try:
            return record_demo_connector_manifest(repository, bound_manifest)
        except ConnectorManifestConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.POLICY_VIOLATION.value,
                    "message": "The connector manifest already exists.",
                    "reason": "manifest_already_exists",
                    "connector_id": exc.connector_id,
                },
            ) from exc
        except ConnectorManifestValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                    "errors": [error.model_dump() for error in exc.errors],
                },
            ) from exc

    @operations_router.get(
        "/connectors/manifests/{connector_id}",
        response_model=ConnectorManifestDetail,
        responses={
            403: {"description": "Connector manifest read permission denied"},
            404: {"description": "Connector manifest not found"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_manifest_detail(
        connector_id: str,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
    ) -> ConnectorManifestDetail:
        _authorize_tenant_read(tenant_id, principal)
        try:
            return get_connector_manifest_detail(repository, tenant_id, connector_id)
        except ConnectorManifestNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "The connector manifest was not found for this tenant.",
                    "connector_id": connector_id,
                },
            ) from exc

    @operations_router.put(
        "/connectors/manifests/{connector_id}",
        response_model=ConnectorManifestRecordView,
        responses={
            403: {"description": "Connector manifest actor binding permission denied"},
            404: {"description": "Connector manifest not found"},
            409: {"description": "Connector manifest revision conflict"},
            422: {"description": "Connector manifest validation failed"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_manifest_replace(
        connector_id: str,
        replace_request: ConnectorManifestReplaceRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> ConnectorManifestRecordView:
        bound_request = _bind_connector_run_actor(
            replace_request,
            principal,
            actor_field="registered_by",
        )
        request_connector_id = bound_request.manifest.get("connector_id")
        if connector_id != request_connector_id:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "The path connector_id must match the manifest connector_id.",
                    "reason": "connector_id_mismatch",
                },
            )
        try:
            return replace_demo_connector_manifest(repository, bound_request)
        except ConnectorManifestNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "The connector manifest was not found for this tenant.",
                    "connector_id": connector_id,
                },
            ) from exc
        except ConnectorManifestRevisionConflict as exc:
            detail = {
                "code": AxisErrorCode.POLICY_VIOLATION.value,
                "message": ("The connector manifest revision conflicts with persisted state."),
                "reason": exc.reason,
                "connector_id": exc.connector_id,
            }
            if exc.current_revision_number is not None:
                detail["current_revision_number"] = exc.current_revision_number
            raise HTTPException(status_code=409, detail=detail) from exc
        except ConnectorManifestValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                    "errors": [error.model_dump() for error in exc.errors],
                },
            ) from exc

    @operations_router.post(
        "/connectors/manifests/validation",
        response_model=ConnectorManifestBatchValidationResponse,
        responses={
            403: {"description": "Connector manifest actor binding permission denied"},
            422: {"description": "Connector manifest validation request failed"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_manifest_validation(
        validation_request: ConnectorManifestBatchValidationRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> ConnectorManifestBatchValidationResponse:
        bound_request = _bind_connector_run_actor(
            validation_request,
            principal,
            actor_field="registered_by",
        )
        if len(bound_request.manifests) > MANIFEST_VALIDATION_BATCH_LIMIT:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": (
                        "Connector manifest validation accepts at most "
                        f"{MANIFEST_VALIDATION_BATCH_LIMIT} manifests per request."
                    ),
                    "reason": "manifest_validation_batch_limit_exceeded",
                    "maximum": MANIFEST_VALIDATION_BATCH_LIMIT,
                },
            )
        return validate_connector_manifest_batch(repository, bound_request)

    @operations_router.post(
        "/connectors/manifests/{connector_id}/lifecycle",
        response_model=ConnectorManifestRecordView,
        responses={
            403: {"description": "Connector manifest lifecycle permission denied"},
            422: {"description": "Connector manifest lifecycle validation failed"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_manifest_lifecycle(
        connector_id: str,
        lifecycle_request: ConnectorManifestLifecycleRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> ConnectorManifestRecordView:
        bound_lifecycle = _bind_connector_run_actor(
            lifecycle_request,
            principal,
            actor_field="transitioned_by",
        )
        try:
            return transition_demo_connector_manifest_lifecycle(
                repository,
                connector_id,
                bound_lifecycle,
            )
        except ConnectorManifestLifecycleValidationError as exc:
            scope_denial = exc.reason in {
                "missing_manifest_lifecycle_scope",
                "missing_manifest_live_scope",
            }
            # Scope denials carry the same permission-denied contract as every
            # other governed write; only transition-legality failures are
            # validation errors.
            status_code = 403 if scope_denial else 422
            raise HTTPException(
                status_code=status_code,
                detail={
                    "code": (
                        AxisErrorCode.PERMISSION_DENIED.value
                        if scope_denial
                        else AxisErrorCode.VALIDATION_FAILED.value
                    ),
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.get(
        "/connectors/configurations",
        response_model=ManufacturingConnectorConfigurationRegistry,
        responses={403: {"description": "Connector configuration read permission denied"}},
        tags=["demo"],
    )
    def manufacturing_connector_configurations(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        connector_id: str | None = Query(default=None, min_length=1),
        status: str | None = Query(default=None, min_length=1),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> ManufacturingConnectorConfigurationRegistry:
        _authorize_tenant_read(tenant_id, principal)
        return build_connector_configuration_registry(
            repository,
            ConnectorConfigurationQuery(
                tenant_id=tenant_id,
                connector_id=connector_id,
                status=status,
                limit=limit,
            ),
        )

    @operations_router.post(
        "/connectors/configurations",
        response_model=ConnectorTenantConfiguration,
        responses={
            403: {"description": "Connector configuration actor binding permission denied"},
            404: {"description": "Connector registry reference record not found"},
            422: {"description": "Connector configuration or registry reference validation failed"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    def manufacturing_connector_configuration_create(
        configuration: ConnectorConfigurationCreateRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> ConnectorTenantConfiguration:
        bound_configuration = _bind_connector_run_actor(
            configuration,
            principal,
            actor_field="created_by",
        )
        try:
            return record_demo_connector_configuration(repository, bound_configuration)
        except ConnectorReferenceRecordNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "Manufacturing connector registry reference record not found.",
                    "surface": "connectors",
                },
            ) from exc
        except ConnectorReferenceRecordInvalid as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "Manufacturing connector registry reference payload is invalid.",
                    "surface": "connectors",
                },
            ) from exc
        except ConnectorConfigurationValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.get(
        "/connectors/credential-handles",
        response_model=ManufacturingConnectorCredentialHandleRegistry,
        responses={403: {"description": "Connector credential handle read permission denied"}},
        tags=["demo"],
    )
    def manufacturing_connector_credential_handles(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        connector_id: str | None = Query(default=None, min_length=1),
        status: str | None = Query(default=None, min_length=1),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> ManufacturingConnectorCredentialHandleRegistry:
        _authorize_tenant_read(tenant_id, principal)
        return build_connector_credential_handle_registry(
            repository,
            ConnectorCredentialHandleQuery(
                tenant_id=tenant_id,
                connector_id=connector_id,
                status=status,
                limit=limit,
            ),
        )

    @operations_router.post(
        "/connectors/credential-handles",
        response_model=ConnectorCredentialHandleRecord,
        responses={
            403: {"description": "Connector credential handle actor binding permission denied"},
            404: {"description": "Connector registry reference record not found"},
            422: {"description": "Connector credential handle or registry validation failed"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    def manufacturing_connector_credential_handle_create(
        credential_handle: ConnectorCredentialHandleCreateRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> ConnectorCredentialHandleRecord:
        bound_handle = _bind_connector_run_actor(
            credential_handle,
            principal,
            actor_field="created_by",
        )
        try:
            return record_demo_connector_credential_handle(repository, bound_handle)
        except ConnectorReferenceRecordNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "Manufacturing connector registry reference record not found.",
                    "surface": "connectors",
                },
            ) from exc
        except ConnectorReferenceRecordInvalid as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "Manufacturing connector registry reference payload is invalid.",
                    "surface": "connectors",
                },
            ) from exc
        except ConnectorCredentialHandleValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.post(
        "/connectors/credential-handles/{handle_id}/rotations",
        response_model=ConnectorCredentialHandleRecord,
        responses={
            403: {"description": "Connector credential rotation actor binding permission denied"},
            422: {"description": "Connector credential rotation validation failed"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    def manufacturing_connector_credential_handle_rotation(
        handle_id: str,
        rotation: ConnectorCredentialRotationRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> ConnectorCredentialHandleRecord:
        bound_rotation = _bind_connector_run_actor(
            rotation,
            principal,
            actor_field="rotated_by",
        )
        try:
            return record_demo_connector_credential_rotation(
                repository,
                handle_id,
                bound_rotation,
            )
        except ConnectorCredentialHandleValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.get(
        "/connectors/credential-leases",
        response_model=ManufacturingConnectorCredentialLeaseRegistry,
        responses={403: {"description": "Connector credential lease read permission denied"}},
        tags=["demo"],
    )
    def manufacturing_connector_credential_leases(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        connector_id: str | None = Query(default=None, min_length=1),
        handle_id: str | None = Query(default=None, min_length=1),
        status: str | None = Query(default=None, min_length=1),
        limit: int = Query(default=100, ge=1, le=200),
        actor_id: str = Query(default="connector-credential-lease-reader", min_length=1),
    ) -> ManufacturingConnectorCredentialLeaseRegistry:
        _authorize_tenant_read(tenant_id, principal)
        return read_connector_credential_lease_registry(
            repository,
            ConnectorCredentialLeaseQuery(
                tenant_id=tenant_id,
                connector_id=connector_id,
                handle_id=handle_id,
                status=status,
                limit=limit,
            ),
            actor_id=actor_id,
        )

    @operations_router.post(
        "/connectors/credential-leases",
        response_model=ConnectorCredentialLeaseRecord,
        responses={
            403: {"description": "Connector credential lease permission denied"},
            404: {"description": "Connector registry reference record not found"},
            409: {"description": "Connector credential lease already exists"},
            422: {"description": "Connector credential lease validation failed"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    def manufacturing_connector_credential_lease_create(
        lease_request: ConnectorCredentialLeaseRequest,
        repository: PersistenceRepository,
        lease_runtime: CredentialLeaseRuntimeDependency,
        principal: OidcPrincipalDependency,
    ) -> ConnectorCredentialLeaseRecord:
        bound_lease = _bind_connector_run_actor(
            lease_request,
            principal,
            actor_field="requested_by",
        )
        try:
            return record_demo_connector_credential_lease(
                repository,
                bound_lease,
                lease_runtime,
            )
        except ConnectorReferenceRecordNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "Manufacturing connector registry reference record not found.",
                    "surface": "connectors",
                },
            ) from exc
        except ConnectorReferenceRecordInvalid as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "Manufacturing connector registry reference payload is invalid.",
                    "surface": "connectors",
                },
            ) from exc
        except ConnectorCredentialLeasePermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot request connector credential leases.",
                    "required_permission": exc.required_permission,
                    "reason": "missing_required_scope",
                    "permission_reason": exc.decision.reason,
                },
            ) from exc
        except ConnectorCredentialLeaseConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.POLICY_VIOLATION.value,
                    "message": "The connector credential lease already exists.",
                    "reason": "credential_lease_already_exists",
                    "lease_id": exc.lease_id,
                },
            ) from exc
        except ConnectorCredentialLeaseValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.post(
        "/connectors/credential-leases/{lease_id}/renew",
        response_model=ConnectorCredentialLeaseRecord,
        responses={
            403: {"description": "Connector credential lease permission denied"},
            422: {"description": "Connector credential lease renewal validation failed"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_credential_lease_renew(
        lease_id: str,
        renew_request: ConnectorCredentialLeaseRenewRequest,
        repository: PersistenceRepository,
        lease_runtime: CredentialLeaseRuntimeDependency,
        principal: OidcPrincipalDependency,
    ) -> ConnectorCredentialLeaseRecord:
        bound_renew = _bind_connector_run_actor(
            renew_request,
            principal,
            actor_field="renewed_by",
        )
        try:
            return renew_demo_connector_credential_lease(
                repository,
                lease_id,
                bound_renew,
                lease_runtime,
            )
        except ConnectorCredentialLeasePermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot renew connector credential leases.",
                    "required_permission": exc.required_permission,
                    "reason": "missing_required_scope",
                    "permission_reason": exc.decision.reason,
                },
            ) from exc
        except ConnectorCredentialLeaseValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.post(
        "/connectors/credential-leases/{lease_id}/revoke",
        response_model=ConnectorCredentialLeaseRecord,
        responses={
            403: {"description": "Connector credential lease permission denied"},
            422: {"description": "Connector credential lease revocation validation failed"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_credential_lease_revoke(
        lease_id: str,
        revoke_request: ConnectorCredentialLeaseRevokeRequest,
        repository: PersistenceRepository,
        lease_runtime: CredentialLeaseRuntimeDependency,
        principal: OidcPrincipalDependency,
    ) -> ConnectorCredentialLeaseRecord:
        bound_revoke = _bind_connector_run_actor(
            revoke_request,
            principal,
            actor_field="revoked_by",
        )
        try:
            return revoke_demo_connector_credential_lease(
                repository,
                lease_id,
                bound_revoke,
                lease_runtime,
            )
        except ConnectorCredentialLeasePermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot revoke connector credential leases.",
                    "required_permission": exc.required_permission,
                    "reason": "missing_required_scope",
                    "permission_reason": exc.decision.reason,
                },
            ) from exc
        except ConnectorCredentialLeaseValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.get(
        "/connectors/egress-policies",
        response_model=ManufacturingConnectorEgressPolicyRegistry,
        responses={403: {"description": "Connector egress policy read permission denied"}},
        tags=["demo"],
    )
    def manufacturing_connector_egress_policies(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        connector_id: str | None = Query(default=None, min_length=1),
        status: str | None = Query(default=None, min_length=1),
        limit: int = Query(default=100, ge=1, le=200),
        actor_id: str = Query(default="connector-egress-policy-reader", min_length=1),
    ) -> ManufacturingConnectorEgressPolicyRegistry:
        _authorize_tenant_read(tenant_id, principal)
        return read_connector_egress_policy_registry(
            repository,
            ConnectorEgressPolicyQuery(
                tenant_id=tenant_id,
                connector_id=connector_id,
                status=status,
                limit=limit,
            ),
            actor_id=actor_id,
        )

    @operations_router.post(
        "/connectors/egress-policies",
        response_model=ConnectorEgressPolicyRecord,
        responses={
            403: {"description": "Connector egress policy actor binding permission denied"},
            422: {"description": "Connector egress policy validation failed"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    def manufacturing_connector_egress_policy_create(
        egress_policy: ConnectorEgressPolicyCreateRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> ConnectorEgressPolicyRecord:
        bound_policy = _bind_connector_run_actor(
            egress_policy,
            principal,
            actor_field="created_by",
        )
        try:
            return record_demo_connector_egress_policy(repository, bound_policy)
        except ConnectorEgressPolicyValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.get(
        "/connectors/evidence-invariants",
        response_model=ManufacturingConnectorEvidenceInvariantReport,
        responses={403: {"description": "Connector evidence invariant read permission denied"}},
        tags=["demo"],
    )
    def manufacturing_connector_evidence_invariants(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        connector_id: str | None = Query(default=None, min_length=1),
        limit: int = Query(default=100, ge=1, le=200),
        actor_id: str = Query(default="connector-evidence-report-reader", min_length=1),
    ) -> ManufacturingConnectorEvidenceInvariantReport:
        _authorize_tenant_read(tenant_id, principal)
        return read_connector_evidence_invariant_report(
            repository,
            ConnectorEvidenceInvariantQuery(
                tenant_id=tenant_id,
                connector_id=connector_id,
                limit=limit,
            ),
            actor_id=actor_id,
        )

    @operations_router.post(
        "/connectors/evidence-invariants/snapshots",
        response_model=ConnectorEvidenceInvariantSnapshotRecord,
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
        responses={
            403: {"description": "Connector evidence snapshot permission denied"},
            409: {"description": "Connector evidence snapshot idempotency conflict"},
        },
    )
    def manufacturing_connector_evidence_invariant_snapshot(
        request: ConnectorEvidenceInvariantSnapshotRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> ConnectorEvidenceInvariantSnapshotRecord:
        bound_request = _bind_connector_run_actor(
            request,
            principal,
            actor_field="requested_by",
        )
        try:
            return persist_connector_evidence_invariant_snapshot(repository, bound_request)
        except ConnectorEvidenceInvariantSnapshotPermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot persist connector evidence snapshots.",
                    "required_scope": "connectors:evidence:snapshot",
                    "decision": exc.decision.model_dump(),
                },
            ) from exc
        except ConnectorEvidenceInvariantSnapshotConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.CONFLICT.value,
                    "message": "The connector evidence snapshot idempotency key conflicts.",
                    "snapshot_id": exc.snapshot_id,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.get(
        "/connectors/evidence-invariants/snapshots/export",
        response_model=ConnectorEvidenceInvariantSnapshotExportBundle,
        tags=["demo"],
        responses={
            403: {"description": "Connector evidence snapshot export permission denied"},
        },
    )
    def manufacturing_connector_evidence_invariant_snapshot_export(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        connector_id: str | None = Query(default=None, min_length=1),
        snapshot_id: str | None = Query(default=None, min_length=1),
        idempotency_key: str | None = Query(default=None, min_length=1),
        actor_id: str = Query(default="connector-evidence-exporter-role", min_length=1),
        actor_scopes: list[str] = CheckpointActorScopesQuery,
        limit: int = Query(default=100, ge=1, le=200),
        export_reason: str = Query(
            default="connector-evidence-review",
            min_length=1,
            max_length=120,
        ),
        format: str = Query(default="json", pattern="^json$"),
    ) -> ConnectorEvidenceInvariantSnapshotExportBundle:
        _authorize_tenant_read(tenant_id, principal)
        resolved_actor_id = principal.actor_id if principal is not None else actor_id
        resolved_actor_scopes = principal.scopes if principal is not None else actor_scopes
        try:
            return export_connector_evidence_invariant_snapshots(
                repository,
                ConnectorEvidenceInvariantSnapshotExportQuery(
                    tenant_id=tenant_id,
                    connector_id=connector_id,
                    snapshot_id=snapshot_id,
                    idempotency_key=idempotency_key,
                    limit=limit,
                    export_reason=export_reason,
                    format=format,
                ),
                actor_id=resolved_actor_id,
                actor_scopes=resolved_actor_scopes,
                ledger_signer=_audit_ledger_signer_from_settings(app.state.settings),
            )
        except ConnectorEvidenceInvariantSnapshotPermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot export connector evidence snapshots.",
                    "required_scope": "connectors:evidence:snapshot:read",
                    "decision": exc.decision.model_dump(),
                },
            ) from exc

    @operations_router.post(
        "/connectors/evidence-invariants/snapshots/export-requests",
        response_model=ConnectorEvidenceInvariantSnapshotExportRequestRecord,
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
        responses={
            403: {"description": "Connector evidence snapshot export request permission denied"},
            409: {"description": "Connector evidence snapshot export request conflict"},
        },
    )
    def manufacturing_connector_evidence_invariant_snapshot_export_request(
        request: ConnectorEvidenceInvariantSnapshotExportRequest,
        repository: PersistenceRepository,
        response: Response,
        principal: OidcPrincipalDependency,
    ) -> ConnectorEvidenceInvariantSnapshotExportRequestRecord:
        bound_request = _bind_connector_run_actor(
            request,
            principal,
            actor_field="requested_by",
        )
        try:
            result = record_connector_evidence_invariant_snapshot_export_request(
                repository,
                bound_request,
            )
        except ConnectorEvidenceInvariantSnapshotPermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": ("The actor cannot request connector evidence snapshot exports."),
                    "required_scope": "connectors:evidence:snapshot:export:request",
                    "decision": exc.decision.model_dump(),
                },
            ) from exc
        except ConnectorEvidenceInvariantSnapshotExportRequestConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.CONFLICT.value,
                    "message": ("The connector evidence snapshot export request conflicts."),
                    "export_request_id": exc.export_request_id,
                    "reason": exc.reason,
                },
            ) from exc
        if result.idempotent_replay:
            response.status_code = status.HTTP_200_OK
        return result

    @operations_router.post(
        "/connectors/evidence-invariants/snapshots/export-requests/{export_request_id}/decision",
        response_model=ConnectorEvidenceInvariantSnapshotExportDecisionResult,
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
        responses={
            403: {"description": "Connector evidence snapshot export decision denied"},
            404: {"description": "Connector evidence snapshot export request not found"},
        },
    )
    async def manufacturing_connector_evidence_invariant_snapshot_export_request_decision(
        export_request_id: str,
        decision: ConnectorEvidenceInvariantSnapshotExportDecisionRequest,
        repository: PersistenceRepository,
        runtime: WorkflowRuntime,
        principal: OidcPrincipalDependency,
    ) -> ConnectorEvidenceInvariantSnapshotExportDecisionResult:
        try:
            bound_decision = _bind_demo_actor(decision, principal)
            return await record_connector_evidence_invariant_snapshot_export_request_decision(
                repository,
                export_request_id,
                bound_decision,
                runtime,
            )
        except ConnectorEvidenceInvariantSnapshotExportRequestNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail="Connector evidence snapshot export request not found",
            ) from exc
        except ConnectorEvidenceInvariantSnapshotExportDecisionPermissionDenied as exc:
            reason = (
                "missing_required_scope"
                if exc.decision.reason.startswith("missing_scope:")
                else exc.decision.reason
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": ("The actor cannot decide connector evidence snapshot exports."),
                    "required_scope": exc.required_permission,
                    "decision": exc.decision.model_dump(),
                    "reason": reason,
                    "permission_reason": exc.decision.reason,
                },
            ) from exc

    @operations_router.post(
        "/connectors/evidence-invariants/snapshots/"
        "export-requests/{export_request_id}/materializations",
        response_model=ConnectorEvidenceInvariantSnapshotExportMaterializationResult,
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
        responses={
            403: {"description": "Connector evidence snapshot export materialization denied"},
            404: {"description": "Connector evidence snapshot export request not found"},
            409: {"description": "Connector evidence snapshot export materialization conflict"},
        },
    )
    def manufacturing_connector_evidence_invariant_snapshot_export_materialization(
        export_request_id: str,
        materialization: ConnectorEvidenceInvariantSnapshotExportMaterializationRequest,
        repository: PersistenceRepository,
        object_store: ConnectorExportObjectStore,
        principal: OidcPrincipalDependency,
    ) -> ConnectorEvidenceInvariantSnapshotExportMaterializationResult:
        try:
            bound_materialization = _bind_demo_actor(materialization, principal)
            return materialize_connector_evidence_invariant_snapshot_export_request(
                repository,
                export_request_id,
                bound_materialization,
                object_store,
                ledger_signer=_audit_ledger_signer_from_settings(app.state.settings),
            )
        except ConnectorEvidenceInvariantSnapshotExportRequestNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail="Connector evidence snapshot export request not found",
            ) from exc
        except ConnectorEvidenceInvariantSnapshotExportMaterializationPermissionDenied as exc:
            reason = (
                "missing_required_scope"
                if exc.decision.reason.startswith("missing_scope:")
                else exc.decision.reason
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": (
                        "The actor cannot materialize connector evidence snapshot exports."
                    ),
                    "required_scope": exc.required_permission,
                    "decision": exc.decision.model_dump(),
                    "reason": reason,
                    "permission_reason": exc.decision.reason,
                },
            ) from exc
        except ConnectorEvidenceInvariantSnapshotExportMaterializationConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.CONFLICT.value,
                    "message": (
                        "The connector evidence snapshot export materialization conflicts."
                    ),
                    "export_request_id": exc.export_request_id,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.get(
        "/connectors/evidence-invariants/snapshots",
        response_model=ConnectorEvidenceInvariantSnapshotHistory,
        tags=["demo"],
        responses={
            403: {"description": "Connector evidence snapshot history permission denied"},
        },
    )
    def manufacturing_connector_evidence_invariant_snapshot_history(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        connector_id: str | None = Query(default=None, min_length=1),
        snapshot_id: str | None = Query(default=None, min_length=1),
        idempotency_key: str | None = Query(default=None, min_length=1),
        actor_id: str = Query(default="connector-evidence-history-reader", min_length=1),
        actor_scopes: list[str] = CheckpointActorScopesQuery,
        limit: int = Query(default=100, ge=1, le=200),
    ) -> ConnectorEvidenceInvariantSnapshotHistory:
        _authorize_tenant_read(tenant_id, principal)
        try:
            return read_connector_evidence_invariant_snapshot_history(
                repository,
                ConnectorEvidenceInvariantSnapshotQuery(
                    tenant_id=tenant_id,
                    connector_id=connector_id,
                    snapshot_id=snapshot_id,
                    idempotency_key=idempotency_key,
                    limit=limit,
                ),
                actor_id=actor_id,
                actor_scopes=actor_scopes,
            )
        except ConnectorEvidenceInvariantSnapshotPermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot read connector evidence snapshots.",
                    "required_scope": "connectors:evidence:snapshot:read",
                    "decision": exc.decision.model_dump(),
                },
            ) from exc

    @operations_router.get(
        "/connectors/runs",
        response_model=ManufacturingConnectorRunRegistry,
        responses={403: {"description": "Connector run read permission denied"}},
        tags=["demo"],
    )
    def manufacturing_connector_runs(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        connector_id: str | None = Query(default=None, min_length=1),
        status: str | None = Query(default=None, min_length=1),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> ManufacturingConnectorRunRegistry:
        _authorize_tenant_read(tenant_id, principal)
        return build_connector_run_registry(
            repository,
            ConnectorRunQuery(
                tenant_id=tenant_id,
                connector_id=connector_id,
                status=status,
                limit=limit,
            ),
        )

    @operations_router.post(
        "/connectors/runs",
        response_model=ConnectorRunRecord,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Connector run actor binding permission denied"},
            404: {"description": "Connector registry reference record not found"},
            422: {"description": "Connector run or registry validation failed"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    def manufacturing_connector_run_create(
        connector_run: ConnectorRunCreateRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        execution_runtime: ConnectorExecutionRuntimeDependency,
        sync_scheduler_runtime: ConnectorSyncSchedulerRuntimeDependency,
    ) -> ConnectorRunRecord:
        bound_run = _bind_connector_run_actor(
            connector_run,
            principal,
            actor_field="requested_by",
        )
        try:
            return record_demo_connector_run(
                repository,
                bound_run,
                execution_runtime,
                sync_scheduler_runtime,
            )
        except ConnectorReferenceRecordNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "Manufacturing connector registry reference record not found.",
                    "surface": "connectors",
                },
            ) from exc
        except ConnectorReferenceRecordInvalid as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "Manufacturing connector registry reference payload is invalid.",
                    "surface": "connectors",
                },
            ) from exc
        except ConnectorRunValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.get(
        "/connectors/runs/checkpoints",
        response_model=ManufacturingConnectorSyncCheckpointRegistry,
        responses={
            403: {"description": "Connector sync checkpoint read permission denied"},
            422: {"description": "Connector sync checkpoint query validation failed"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_run_checkpoints(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        connector_id: str | None = Query(default=None, min_length=1),
        run_id: str | None = Query(default=None, min_length=1),
        status: str | None = Query(default=None, min_length=1),
        created_after: datetime | None = CheckpointCreatedAfterQuery,
        created_before: datetime | None = CheckpointCreatedBeforeQuery,
        actor_scopes: list[str] = CheckpointActorScopesQuery,
        limit: int = Query(default=100, ge=1, le=200),
    ) -> ManufacturingConnectorSyncCheckpointRegistry:
        _authorize_connector_sync_checkpoint_read(tenant_id, actor_scopes, principal)
        try:
            return read_connector_sync_checkpoint_registry(
                repository,
                ConnectorSyncCheckpointQuery(
                    tenant_id=tenant_id,
                    connector_id=connector_id,
                    run_id=run_id,
                    status=status,
                    created_after=created_after,
                    created_before=created_before,
                    limit=limit,
                ),
                actor_id=(
                    principal.actor_id
                    if principal is not None
                    else "connector-sync-checkpoint-reader"
                ),
                read_scope_source=(
                    "oidc_principal" if principal is not None else "demo_actor_scopes"
                ),
            )
        except ConnectorRunValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.get(
        "/connectors/runs/checkpoints/claims",
        response_model=ManufacturingConnectorSyncCheckpointClaimRegistry,
        responses={
            403: {"description": "Connector sync checkpoint claim read permission denied"},
            422: {"description": "Connector sync checkpoint claim query validation failed"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_run_checkpoint_claims(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        checkpoint_id: str | None = Query(default=None, min_length=1),
        connector_id: str | None = Query(default=None, min_length=1),
        run_id: str | None = Query(default=None, min_length=1),
        status: str | None = Query(default=None, min_length=1),
        claimed_by: str | None = Query(default=None, min_length=1),
        created_after: datetime | None = CheckpointCreatedAfterQuery,
        created_before: datetime | None = CheckpointCreatedBeforeQuery,
        cursor: str | None = Query(default=None, min_length=1, max_length=600),
        actor_scopes: list[str] = CheckpointActorScopesQuery,
        limit: int = Query(default=100, ge=1, le=200),
    ) -> ManufacturingConnectorSyncCheckpointClaimRegistry:
        _authorize_connector_sync_checkpoint_claim_read(
            tenant_id,
            actor_scopes,
            principal,
        )
        try:
            return read_connector_sync_checkpoint_claim_registry(
                repository,
                ConnectorSyncCheckpointClaimQuery(
                    tenant_id=tenant_id,
                    checkpoint_id=checkpoint_id,
                    connector_id=connector_id,
                    run_id=run_id,
                    status=status,
                    claimed_by=claimed_by,
                    created_after=created_after,
                    created_before=created_before,
                    cursor=cursor,
                    limit=limit,
                ),
                actor_id=(
                    principal.actor_id
                    if principal is not None
                    else "connector-sync-checkpoint-claim-reader"
                ),
                read_scope_source=(
                    "oidc_principal" if principal is not None else "demo_actor_scopes"
                ),
            )
        except ConnectorRunValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.post(
        "/connectors/runs/checkpoints/{checkpoint_id}/claims",
        response_model=ConnectorSyncCheckpointClaimRecord,
        status_code=status.HTTP_201_CREATED,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Connector sync checkpoint claim permission denied"},
            404: {"description": "Connector sync checkpoint not found"},
            409: {"description": "Connector sync checkpoint claim conflict"},
            422: {"description": "Connector sync checkpoint claim validation failed"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_run_checkpoint_claim(
        checkpoint_id: str,
        claim_request: ConnectorSyncCheckpointClaimRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        response: Response,
    ) -> ConnectorSyncCheckpointClaimRecord:
        bound_claim = _bind_connector_run_actor(
            claim_request,
            principal,
            actor_field="claimed_by",
        )
        try:
            claim, created = claim_connector_sync_checkpoint(
                repository,
                checkpoint_id,
                bound_claim,
            )
            if not created:
                response.status_code = status.HTTP_200_OK
            return claim
        except ConnectorRunPermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot claim connector sync checkpoints.",
                    "required_permission": exc.required_permission,
                    "reason": "missing_required_scope",
                },
            ) from exc
        except ConnectorRunNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "The connector sync checkpoint was not found.",
                    "reason": "connector_sync_checkpoint_not_found",
                },
            ) from exc
        except ConnectorSyncCheckpointClaimConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.CONFLICT.value,
                    "message": (
                        "The connector sync checkpoint claim conflicts with existing evidence."
                    ),
                    "reason": exc.reason,
                    "active_claim_id": exc.active_claim_id,
                },
            ) from exc
        except ConnectorRunValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.post(
        "/connectors/runs/checkpoints/{checkpoint_id}/claims/{claim_id}/renew",
        response_model=ConnectorSyncCheckpointClaimRecord,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Connector sync checkpoint claim renew permission denied"},
            404: {"description": "Connector sync checkpoint claim not found"},
            422: {"description": "Connector sync checkpoint claim renew validation failed"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_run_checkpoint_claim_renew(
        checkpoint_id: str,
        claim_id: str,
        renew_request: ConnectorSyncCheckpointClaimRenewRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> ConnectorSyncCheckpointClaimRecord:
        bound_renew = _bind_connector_run_actor(
            renew_request,
            principal,
            actor_field="renewed_by",
        )
        try:
            return renew_connector_sync_checkpoint_claim(
                repository,
                checkpoint_id,
                claim_id,
                bound_renew,
            )
        except ConnectorRunPermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot renew connector sync checkpoint claims.",
                    "required_permission": exc.required_permission,
                    "reason": "missing_required_scope",
                },
            ) from exc
        except ConnectorRunNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "The connector sync checkpoint claim was not found.",
                    "reason": "connector_sync_checkpoint_claim_not_found",
                },
            ) from exc
        except ConnectorRunValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.post(
        "/connectors/runs/checkpoints/{checkpoint_id}/claims/{claim_id}/release",
        response_model=ConnectorSyncCheckpointClaimRecord,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Connector sync checkpoint claim release permission denied"},
            404: {"description": "Connector sync checkpoint claim not found"},
            422: {"description": "Connector sync checkpoint claim release validation failed"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_run_checkpoint_claim_release(
        checkpoint_id: str,
        claim_id: str,
        release_request: ConnectorSyncCheckpointClaimReleaseRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> ConnectorSyncCheckpointClaimRecord:
        bound_release = _bind_connector_run_actor(
            release_request,
            principal,
            actor_field="released_by",
        )
        try:
            return release_connector_sync_checkpoint_claim(
                repository,
                checkpoint_id,
                claim_id,
                bound_release,
            )
        except ConnectorRunPermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot release connector sync checkpoint claims.",
                    "required_permission": exc.required_permission,
                    "reason": "missing_required_scope",
                },
            ) from exc
        except ConnectorRunNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "The connector sync checkpoint claim was not found.",
                    "reason": "connector_sync_checkpoint_claim_not_found",
                },
            ) from exc
        except ConnectorRunValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.post(
        "/connectors/runs/{run_id}/dispatch",
        response_model=ConnectorRunRecord,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Connector sync dispatch permission denied"},
            404: {"description": "Connector run not found"},
            409: {"description": "Connector sync dispatch idempotency conflict"},
            422: {"description": "Connector sync dispatch validation failed"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_run_dispatch(
        run_id: str,
        dispatch_request: ConnectorRunDispatchRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        sync_dispatch_runtime: ConnectorSyncDispatchRuntimeDependency,
    ) -> ConnectorRunRecord:
        bound_dispatch = _bind_connector_run_actor(
            dispatch_request,
            principal,
            actor_field="dispatched_by",
        )
        try:
            return dispatch_demo_connector_sync(
                repository,
                run_id,
                bound_dispatch,
                sync_dispatch_runtime,
            )
        except ConnectorRunPermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot dispatch scheduled connector sync.",
                    "required_permission": exc.required_permission,
                    "reason": "missing_required_scope",
                },
            ) from exc
        except ConnectorRunNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "The connector run was not found.",
                    "reason": "connector_run_not_found",
                },
            ) from exc
        except ConnectorRunDispatchConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.CONFLICT.value,
                    "message": "The connector sync dispatch conflicts with existing evidence.",
                    "reason": exc.reason,
                },
            ) from exc
        except ConnectorRunValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.post(
        "/connectors/runs/{run_id}/execute-sync",
        response_model=ConnectorRunRecord,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Connector sync execution permission denied"},
            404: {"description": "Connector run not found"},
            409: {"description": "Connector sync execution idempotency conflict"},
            422: {"description": "Connector sync execution validation failed"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_run_execute_sync(
        run_id: str,
        execution_request: ConnectorRunSyncExecutionRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        sync_execution_runtime: ConnectorSyncExecutionRuntimeDependency,
        live_sync_runtime: ConnectorLiveSyncRuntimeDependency,
    ) -> ConnectorRunRecord:
        bound_execution = _bind_connector_run_actor(
            execution_request,
            principal,
            actor_field="executed_by",
        )
        try:
            with telemetry.tracer.start_as_current_span("axis.connector_sync.execute") as span:
                set_span_attributes(
                    span,
                    {
                        ATTR_CONNECTOR_ID: getattr(bound_execution, "connector_id", None),
                        ATTR_TENANT_ID: principal.tenant_id if principal else None,
                    },
                )
                record = execute_demo_connector_sync(
                    repository,
                    run_id,
                    bound_execution,
                    sync_execution_runtime,
                    live_sync_runtime=live_sync_runtime,
                    usage_metering_enabled=resolved_settings.usage_metering_enabled,
                    usage_window_seconds=(
                        resolved_settings.usage_metering_aggregation_window_seconds
                    ),
                )
                rows = _connector_sync_rows(record)
                set_span_attributes(span, {ATTR_OUTCOME: record.status})
                if rows:
                    telemetry.connector_sync_rows_counter.add(
                        rows, {"connector_id": record.connector_id, "status": record.status}
                    )
                return record
        except ConnectorRunPermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot execute scheduled connector sync.",
                    "required_permission": exc.required_permission,
                    "reason": "missing_required_scope",
                },
            ) from exc
        except ConnectorRunNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "The connector run was not found.",
                    "reason": "connector_run_not_found",
                },
            ) from exc
        except ConnectorRunSyncExecutionConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.CONFLICT.value,
                    "message": "The connector sync execution conflicts with existing evidence.",
                    "reason": exc.reason,
                },
            ) from exc
        except ConnectorRunValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.get(
        "/connectors/ontology-proposals",
        response_model=ManufacturingConnectorOntologyProposalRegistry,
        responses={403: {"description": "Connector ontology proposal read permission denied"}},
        tags=["demo"],
    )
    def manufacturing_connector_ontology_proposals(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        connector_id: str | None = Query(default=None, min_length=1),
        status: str | None = Query(default=None, min_length=1),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> ManufacturingConnectorOntologyProposalRegistry:
        _authorize_tenant_read(tenant_id, principal)
        return build_connector_ontology_proposal_registry(
            repository,
            ConnectorOntologyProposalQuery(
                tenant_id=tenant_id,
                connector_id=connector_id,
                status=status,
                limit=limit,
            ),
        )

    @operations_router.post(
        "/connectors/ontology-proposals",
        response_model=ManufacturingConnectorOntologyProposalRegistry,
        responses={
            403: {"description": "Connector ontology proposal actor binding permission denied"},
            404: {"description": "Connector registry reference record not found"},
            422: {"description": "Connector ontology proposal or registry validation failed"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    def manufacturing_connector_ontology_proposal_create(
        proposal_request: ConnectorOntologyProposalCreateRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> ManufacturingConnectorOntologyProposalRegistry:
        bound_proposal = _bind_connector_run_actor(
            proposal_request,
            principal,
            actor_field="proposed_by",
        )
        try:
            return record_demo_connector_ontology_proposals(repository, bound_proposal)
        except ConnectorReferenceRecordNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "Manufacturing connector registry reference record not found.",
                    "surface": "connectors",
                },
            ) from exc
        except ConnectorReferenceRecordInvalid as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "Manufacturing connector registry reference payload is invalid.",
                    "surface": "connectors",
                },
            ) from exc
        except ConnectorOntologyProposalValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.post(
        "/connectors/ontology-proposals/promotions",
        response_model=ConnectorOntologyPromotionResult,
        responses={
            403: {"description": "Connector ontology promotion permission denied"},
            404: {"description": "Connector ontology proposal not found"},
            409: {"description": "Connector ontology promotion idempotency conflict"},
            422: {"description": "Connector ontology promotion validation failed"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    def manufacturing_connector_ontology_promotion(
        promotion_request: ConnectorOntologyPromotionRequest,
        repository: PersistenceRepository,
        ontology_runtime: OntologyMutationRuntimeDependency,
        principal: OidcPrincipalDependency,
        response: Response,
    ) -> ConnectorOntologyPromotionResult:
        try:
            bound_promotion = _bind_demo_actor(promotion_request, principal)
            result = record_demo_connector_ontology_promotion(
                repository,
                bound_promotion,
                ontology_runtime,
            )
        except ConnectorReferenceRecordNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "Manufacturing connector registry reference record not found.",
                    "surface": "connectors",
                },
            ) from exc
        except ConnectorReferenceRecordInvalid as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "Manufacturing connector registry reference payload is invalid.",
                    "surface": "connectors",
                },
            ) from exc
        except ConnectorOntologyPromotionNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail="Connector ontology proposal not found",
            ) from exc
        except ConnectorOntologyPromotionPermissionDenied as exc:
            reason = (
                "missing_required_scope"
                if exc.decision.reason.startswith("missing_scope:")
                else exc.decision.reason
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot promote this connector ontology proposal.",
                    "required_permission": exc.required_permission,
                    "reason": reason,
                    "permission_reason": exc.decision.reason,
                },
            ) from exc
        except ConnectorOntologyPromotionIdempotencyConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.POLICY_VIOLATION.value,
                    "message": "The idempotency key already exists with a different payload.",
                    "reason": "idempotency_conflict",
                    "promotion_id": exc.promotion_id,
                },
            ) from exc
        except ConnectorOntologyPromotionValidationError as exc:
            detail = {
                "code": AxisErrorCode.VALIDATION_FAILED.value,
                "message": exc.message,
                "reason": exc.reason,
            }
            if exc.audit_event_id is not None:
                repository.session.commit()
                detail["audit_event_id"] = str(exc.audit_event_id)
            if exc.audit_event_type is not None:
                detail["audit_event_type"] = exc.audit_event_type
            raise HTTPException(
                status_code=422,
                detail=detail,
            ) from exc

        if result.idempotent_replay:
            response.status_code = status.HTTP_200_OK

        return result

    @operations_router.get(
        "/connectors/promotion-policies",
        response_model=ManufacturingConnectorPromotionPolicyRegistry,
        responses={403: {"description": "Connector promotion policy read permission denied"}},
        tags=["demo"],
    )
    def manufacturing_connector_promotion_policies(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        connector_id: str | None = Query(default=None, min_length=1),
        status: str | None = Query(default=None, min_length=1),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> ManufacturingConnectorPromotionPolicyRegistry:
        _authorize_tenant_read(tenant_id, principal)
        query = ConnectorPromotionPolicyQuery(
            tenant_id=tenant_id,
            connector_id=connector_id,
            status=status,
            limit=limit,
        )
        return build_connector_promotion_policy_registry(
            repository,
            tenant_id=query.tenant_id,
            connector_id=query.connector_id,
            status=query.status,
            limit=query.limit,
        )

    @operations_router.post(
        "/connectors/promotion-policies",
        response_model=ConnectorPromotionPolicyRecord,
        responses={
            403: {"description": "Connector promotion policy permission denied"},
            404: {"description": "Connector registry reference record not found"},
            409: {"description": "Connector promotion policy already exists"},
            422: {"description": "Connector promotion policy or registry validation failed"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    def manufacturing_connector_promotion_policy_create(
        policy_request: ConnectorPromotionPolicyCreateRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> ConnectorPromotionPolicyRecord:
        try:
            bound_policy = _bind_demo_created_by(policy_request, principal)
            return record_demo_connector_promotion_policy(repository, bound_policy)
        except ConnectorReferenceRecordNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "Manufacturing connector registry reference record not found.",
                    "surface": "connectors",
                },
            ) from exc
        except ConnectorReferenceRecordInvalid as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "Manufacturing connector registry reference payload is invalid.",
                    "surface": "connectors",
                },
            ) from exc
        except ConnectorPromotionPolicyPermissionDenied as exc:
            reason = (
                "missing_required_scope"
                if exc.decision.reason.startswith("missing_scope:")
                else exc.decision.reason
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot author connector promotion policies.",
                    "required_permission": exc.required_permission,
                    "reason": reason,
                    "permission_reason": exc.decision.reason,
                },
            ) from exc
        except ConnectorPromotionPolicyConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.POLICY_VIOLATION.value,
                    "message": "The connector promotion policy already exists.",
                    "reason": "policy_already_exists",
                    "policy_id": exc.policy_id,
                },
            ) from exc
        except ConnectorPromotionPolicyValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.post(
        "/connectors/promotion-policies/{policy_id}/enable",
        response_model=ConnectorPromotionPolicyRecord,
        responses={
            403: {"description": "Connector promotion policy enable permission denied"},
            404: {"description": "Connector promotion policy or registry reference not found"},
            422: {"description": "Connector promotion policy enable or registry validation failed"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_promotion_policy_enable(
        policy_id: str,
        enable_request: ConnectorPromotionPolicyEnableRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> ConnectorPromotionPolicyRecord:
        if policy_id != enable_request.policy_id:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "The path policy_id must match the request policy_id.",
                    "reason": "policy_id_mismatch",
                },
            )
        try:
            bound_request = _bind_demo_enabled_by(enable_request, principal)
            return enable_demo_connector_promotion_policy(repository, bound_request)
        except ConnectorReferenceRecordNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "Manufacturing connector registry reference record not found.",
                    "surface": "connectors",
                },
            ) from exc
        except ConnectorReferenceRecordInvalid as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "Manufacturing connector registry reference payload is invalid.",
                    "surface": "connectors",
                },
            ) from exc
        except ConnectorPromotionPolicyNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail="Connector promotion policy not found",
            ) from exc
        except ConnectorPromotionPolicyPermissionDenied as exc:
            reason = (
                "missing_required_scope"
                if exc.decision.reason.startswith("missing_scope:")
                else exc.decision.reason
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot enable connector promotion policies.",
                    "required_permission": exc.required_permission,
                    "reason": reason,
                    "permission_reason": exc.decision.reason,
                },
            ) from exc
        except ConnectorPromotionPolicyValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.post(
        "/connectors/promotion-policies/{policy_id}/revise",
        response_model=ConnectorPromotionPolicyRecord,
        responses={
            403: {"description": "Connector promotion policy revision permission denied"},
            404: {"description": "Connector promotion policy or registry reference not found"},
            409: {"description": "Connector promotion policy revision conflict"},
            422: {
                "description": ("Connector promotion policy revision or registry validation failed")
            },
        },
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    def manufacturing_connector_promotion_policy_revise(
        policy_id: str,
        revise_request: ConnectorPromotionPolicyReviseRequest,
        response: Response,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> ConnectorPromotionPolicyRecord:
        if policy_id != revise_request.revises_policy_id:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "The path policy_id must match the request revises_policy_id.",
                    "reason": "policy_revision_target_mismatch",
                },
            )
        try:
            bound_request = _bind_demo_updated_by(revise_request, principal)
            result = revise_demo_connector_promotion_policy(repository, bound_request)
        except ConnectorReferenceRecordNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "Manufacturing connector registry reference record not found.",
                    "surface": "connectors",
                },
            ) from exc
        except ConnectorReferenceRecordInvalid as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "Manufacturing connector registry reference payload is invalid.",
                    "surface": "connectors",
                },
            ) from exc
        except ConnectorPromotionPolicyNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail="Connector promotion policy not found",
            ) from exc
        except ConnectorPromotionPolicyPermissionDenied as exc:
            reason = (
                "missing_required_scope"
                if exc.decision.reason.startswith("missing_scope:")
                else exc.decision.reason
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot revise connector promotion policies.",
                    "required_permission": exc.required_permission,
                    "reason": reason,
                    "permission_reason": exc.decision.reason,
                },
            ) from exc
        except ConnectorPromotionPolicyConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.POLICY_VIOLATION.value,
                    "message": "The connector promotion policy already exists.",
                    "reason": "policy_already_exists",
                    "policy_id": exc.policy_id,
                },
            ) from exc
        except ConnectorPromotionPolicyValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

        if result.idempotent_replay:
            response.status_code = status.HTTP_200_OK
        return result

    @operations_router.get(
        "/connectors/promotion-policy-sets",
        response_model=ManufacturingConnectorPromotionPolicySetRegistry,
        responses={403: {"description": "Connector promotion policy set read permission denied"}},
        tags=["demo"],
    )
    def manufacturing_connector_promotion_policy_sets(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        connector_id: str | None = Query(default=None, min_length=1),
        status: str | None = Query(default=None, min_length=1),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> ManufacturingConnectorPromotionPolicySetRegistry:
        _authorize_tenant_read(tenant_id, principal)
        query = ConnectorPromotionPolicySetQuery(
            tenant_id=tenant_id,
            connector_id=connector_id,
            status=status,
            limit=limit,
        )
        return build_connector_promotion_policy_set_registry(
            repository,
            tenant_id=query.tenant_id,
            connector_id=query.connector_id,
            status=query.status,
            limit=query.limit,
        )

    @operations_router.post(
        "/connectors/promotion-policy-sets",
        response_model=ConnectorPromotionPolicySetRecord,
        responses={
            403: {"description": "Connector promotion policy set permission denied"},
            404: {"description": "Connector registry reference record not found"},
            409: {"description": "Connector promotion policy set already exists or active"},
            422: {"description": "Connector promotion policy set or registry validation failed"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    def manufacturing_connector_promotion_policy_set_create(
        policy_set_request: ConnectorPromotionPolicySetActivateRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> ConnectorPromotionPolicySetRecord:
        try:
            bound_request = _bind_demo_activated_by(policy_set_request, principal)
            return record_demo_connector_promotion_policy_set(repository, bound_request)
        except ConnectorReferenceRecordNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "Manufacturing connector registry reference record not found.",
                    "surface": "connectors",
                },
            ) from exc
        except ConnectorReferenceRecordInvalid as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "Manufacturing connector registry reference payload is invalid.",
                    "surface": "connectors",
                },
            ) from exc
        except ConnectorPromotionPolicySetPermissionDenied as exc:
            reason = (
                "missing_required_scope"
                if exc.decision.reason.startswith("missing_scope:")
                else exc.decision.reason
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot activate connector promotion policy sets.",
                    "required_permission": exc.required_permission,
                    "reason": reason,
                    "permission_reason": exc.decision.reason,
                },
            ) from exc
        except ConnectorPromotionPolicySetConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.POLICY_VIOLATION.value,
                    "message": "The connector promotion policy set conflicts with existing state.",
                    "reason": exc.reason,
                    "policy_set_id": exc.policy_set_id,
                },
            ) from exc
        except ConnectorPromotionPolicySetValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.get(
        "/connectors/manual-imports",
        response_model=ManufacturingConnectorManualImportRegistry,
        responses={403: {"description": "Connector manual import read permission denied"}},
        tags=["demo"],
    )
    def manufacturing_connector_manual_imports(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        connector_id: str | None = Query(default=None, min_length=1),
        status: str | None = Query(default=None, min_length=1),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> ManufacturingConnectorManualImportRegistry:
        _authorize_tenant_read(tenant_id, principal)
        return build_connector_manual_import_registry(
            repository,
            ConnectorManualImportQuery(
                tenant_id=tenant_id,
                connector_id=connector_id,
                status=status,
                limit=limit,
            ),
        )

    @operations_router.post(
        "/connectors/manual-imports",
        response_model=ConnectorManualImportRecord,
        responses={
            403: {"description": "Connector manual import actor binding permission denied"},
            404: {"description": "Connector registry reference record not found"},
            409: {"description": "Connector manual import idempotency conflict"},
            422: {"description": "Connector manual import or registry validation failed"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    def manufacturing_connector_manual_import_create(
        manual_import_request: ConnectorManualImportCreateRequest,
        repository: PersistenceRepository,
        response: Response,
        principal: OidcPrincipalDependency,
    ) -> ConnectorManualImportRecord:
        bound_import = _bind_connector_run_actor(
            manual_import_request,
            principal,
            actor_field="requested_by",
        )
        try:
            result = record_demo_connector_manual_import(repository, bound_import)
        except ConnectorReferenceRecordNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "Manufacturing connector registry reference record not found.",
                    "surface": "connectors",
                },
            ) from exc
        except ConnectorReferenceRecordInvalid as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "Manufacturing connector registry reference payload is invalid.",
                    "surface": "connectors",
                },
            ) from exc
        except ConnectorManualImportIdempotencyConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.POLICY_VIOLATION.value,
                    "message": "The idempotency key already exists with a different payload.",
                    "reason": "idempotency_conflict",
                    "import_id": exc.import_id,
                },
            ) from exc
        except ConnectorManualImportValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

        if result.idempotent_replay:
            response.status_code = status.HTTP_200_OK

        return result

    @operations_router.post(
        "/connectors/manual-imports/{import_id}/decision",
        response_model=ConnectorManualImportDecisionResult,
        responses={
            403: {"description": "Connector manual import decision permission denied"},
            404: {"description": "Connector manual import request not found"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    async def manufacturing_connector_manual_import_decision(
        import_id: str,
        decision: ConnectorManualImportDecisionRequest,
        repository: PersistenceRepository,
        runtime: WorkflowRuntime,
        principal: OidcPrincipalDependency,
    ) -> ConnectorManualImportDecisionResult:
        try:
            bound_decision = _bind_demo_actor(decision, principal)
            return await record_demo_connector_manual_import_decision(
                repository,
                import_id,
                bound_decision,
                runtime,
            )
        except ConnectorManualImportNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail="Connector manual import not found",
            ) from exc
        except ConnectorManualImportPermissionDenied as exc:
            reason = (
                "missing_required_scope"
                if exc.decision.reason.startswith("missing_scope:")
                else exc.decision.reason
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot decide this connector manual import.",
                    "required_permission": exc.required_permission,
                    "reason": reason,
                    "permission_reason": exc.decision.reason,
                },
            ) from exc

    @operations_router.post(
        "/connectors/file-csv/preview",
        response_model=ConnectorCsvPreviewResult,
        responses={
            403: {"description": "Connector preview tenant binding permission denied"},
            404: {"description": "Connector registry reference record not found"},
            422: {"description": "Connector registry reference payload invalid"},
        },
        tags=["demo"],
    )
    def manufacturing_file_csv_connector_preview(
        preview_request: ConnectorCsvPreviewRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> ConnectorCsvPreviewResult:
        _authorize_tenant_read(preview_request.tenant_id, principal)
        try:
            registry = require_persisted_manufacturing_connector_registry(
                repository,
                tenant_id=preview_request.tenant_id,
            )
            registry = overlay_registered_connector_manifest(
                repository,
                registry,
                preview_request.tenant_id,
                preview_request.connector_id,
            )
            result = preview_file_csv_connector(registry, preview_request)
        except ConnectorReferenceRecordNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "Manufacturing connector registry reference record not found.",
                    "surface": "connectors",
                },
            ) from exc
        except ConnectorReferenceRecordInvalid as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "Manufacturing connector registry reference payload is invalid.",
                    "surface": "connectors",
                },
            ) from exc
        # A ready preview is a real observation of the file's header schema:
        # recording it keeps discovery evidence-derived instead of invented.
        if result.preview_status == "ready" and result.observed_schema is not None:
            record_data_resource_observation(
                repository,
                tenant_id=preview_request.tenant_id,
                connector_id=preview_request.connector_id,
                file_name=result.file_name,
                columns=list(result.observed_schema.columns),
                observed_by=resolve_declared_actor(
                    None,
                    principal.actor_id if principal is not None else None,
                ),
            )
        return result

    @operations_router.post(
        "/connectors/external-db/preview",
        response_model=ConnectorExternalDbPreviewResult,
        responses={
            403: {"description": "Connector preview tenant binding permission denied"},
            404: {"description": "Connector registry reference record not found"},
            422: {"description": "Connector registry reference payload invalid"},
        },
        tags=["demo"],
    )
    def manufacturing_external_db_connector_preview(
        preview_request: ConnectorExternalDbPreviewRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> ConnectorExternalDbPreviewResult:
        _authorize_tenant_read(preview_request.tenant_id, principal)
        try:
            registry = require_persisted_manufacturing_connector_registry(
                repository,
                tenant_id=preview_request.tenant_id,
            )
            registry = overlay_registered_connector_manifest(
                repository,
                registry,
                preview_request.tenant_id,
                preview_request.connector_id,
            )
            return preview_external_db_connector(registry, preview_request)
        except ConnectorReferenceRecordNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "Manufacturing connector registry reference record not found.",
                    "surface": "connectors",
                },
            ) from exc
        except ConnectorReferenceRecordInvalid as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "Manufacturing connector registry reference payload is invalid.",
                    "surface": "connectors",
                },
            ) from exc

    @operations_router.post(
        "/connectors/external-db/verify-source",
        response_model=SourceVerificationOutcome,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Source verification scope or tenant binding denied"},
            404: {"description": "Credential lease or egress policy not found"},
            422: {"description": "Verification references do not match the connector"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_source_verify(
        verify_request: ConnectorSourceVerifyRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        discovery_runtime: ConnectorSourceDiscoveryRuntimeDependency,
    ) -> SourceVerificationOutcome:
        _authorize_tenant_read(verify_request.tenant_id, principal)
        bound_request = _bind_body_tenant_actor(
            verify_request,
            principal,
            actor_field="requested_by",
            tenant_mismatch_message=(
                "The authenticated OIDC tenant cannot access this connector source."
            ),
        )
        try:
            return record_connector_source_verification(
                repository,
                runtime=discovery_runtime,
                request=bound_request,
                principal_scopes=bound_request.actor_scopes,
            )
        except SourceScopeDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": (
                        "The actor lacks the source discovery scope required for "
                        "connector source verification."
                    ),
                    "required_permission": exc.required_scope,
                    "reason": f"missing_scope:{exc.required_scope}",
                },
            ) from exc
        except ConnectorSourceOperationError as exc:
            status_code = 404 if exc.reason.endswith("_not_found") else 422
            raise HTTPException(
                status_code=status_code,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.post(
        "/connectors/external-db/discover",
        response_model=SourceDiscoveryOutcome,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Source discovery scope or tenant binding denied"},
            404: {"description": "Credential lease or egress policy not found"},
            422: {"description": "Discovery references do not match the connector"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_source_discovery(
        discovery_request: ConnectorSourceDiscoveryRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        discovery_runtime: ConnectorSourceDiscoveryRuntimeDependency,
    ) -> SourceDiscoveryOutcome:
        _authorize_tenant_read(discovery_request.tenant_id, principal)
        bound_request = _bind_body_tenant_actor(
            discovery_request,
            principal,
            actor_field="requested_by",
            tenant_mismatch_message=(
                "The authenticated OIDC tenant cannot access this connector source."
            ),
        )
        try:
            return record_connector_source_discovery(
                repository,
                runtime=discovery_runtime,
                request=bound_request,
                principal_scopes=bound_request.actor_scopes,
            )
        except SourceScopeDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": (
                        "The actor lacks the source discovery scope required for "
                        "connector schema discovery."
                    ),
                    "required_permission": exc.required_scope,
                    "reason": f"missing_scope:{exc.required_scope}",
                },
            ) from exc
        except ConnectorSourceOperationError as exc:
            status_code = 404 if exc.reason.endswith("_not_found") else 422
            raise HTTPException(
                status_code=status_code,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.post(
        "/connectors/external-db/source-bindings",
        response_model=ConnectorSourceActivationOutcome,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Source activation scope or tenant binding denied"},
            404: {"description": "Credential lease or egress policy not found"},
            409: {"description": "An active binding or binding ID already exists"},
            422: {
                "description": (
                    "Activation selections are invalid, stale, duplicate, or oversized"
                )
            },
        },
        tags=["demo"],
    )
    def manufacturing_connector_source_activation(
        activation_request: ConnectorSourceActivationRequest,
        request: Request,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> ConnectorSourceActivationOutcome:
        settings: Settings = request.app.state.settings
        _authorize_tenant_read(activation_request.tenant_id, principal)
        bound_request = _bind_body_tenant_actor(
            activation_request,
            principal,
            actor_field="requested_by",
            tenant_mismatch_message=(
                "The authenticated OIDC tenant cannot activate sources for this connector."
            ),
        )
        try:
            return record_connector_source_activation(
                repository,
                request=bound_request,
                principal_scopes=bound_request.actor_scopes,
                max_selections=settings.connector_source_activation_max_selections,
            )
        except SourceActivationScopeDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": (
                        "The actor lacks the source activation scope required for "
                        "binding discovered tables."
                    ),
                    "required_permission": exc.required_scope,
                    "reason": f"missing_scope:{exc.required_scope}",
                },
            ) from exc
        except ConnectorSourceActivationConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.CONFLICT.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc
        except ConnectorSourceOperationError as exc:
            status_code = 404 if exc.reason.endswith("_not_found") else 422
            raise HTTPException(
                status_code=status_code,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc
        except ConnectorSourceActivationError as exc:
            detail: dict[str, object] = {
                "code": AxisErrorCode.VALIDATION_FAILED.value,
                "message": exc.message,
                "reason": exc.reason,
            }
            if exc.selection_index is not None:
                detail["selection_index"] = exc.selection_index
            raise HTTPException(status_code=422, detail=detail) from exc

    @operations_router.get(
        "/connectors/external-db/source-bindings",
        response_model=ConnectorSourceBindingsView,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Tenant binding denied"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_source_bindings(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        connector_id: str = Query(default="external_db_operational_mirror", min_length=1),
    ) -> ConnectorSourceBindingsView:
        _authorize_tenant_read(tenant_id, principal)
        return list_connector_source_bindings(
            repository,
            tenant_id=tenant_id,
            connector_id=connector_id,
        )

    @operations_router.get(
        "/connectors/external-db/source-ingestion/eligibility",
        response_model=SourceIngestionEligibilityView,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Source ingestion read scope or tenant binding denied"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_source_ingestion_eligibility(
        request: Request,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        connector_id: str = Query(default="external_db_operational_mirror", min_length=1),
        actor_scopes: list[str] = CheckpointActorScopesQuery,
    ) -> SourceIngestionEligibilityView:
        settings: Settings = request.app.state.settings
        _authorize_tenant_read(tenant_id, principal)
        _authorize_source_ingestion_read(
            principal,
            actor_scopes,
            operation="inspect ingestion eligibility",
        )
        rows = preview_source_ingestion_eligibility(
            repository,
            tenant_id=tenant_id,
            connector_id=connector_id,
        )
        return SourceIngestionEligibilityView(
            tenant_id=tenant_id,
            connector_id=connector_id,
            extraction_available=(
                settings.source_ingestion_dispatch_enabled
                and settings.source_ingestion_extraction_enabled
            ),
            planned_limits=planned_extraction_limits(settings),
            rows=rows,
        )

    @operations_router.get(
        "/connectors/external-db/source-ingestion/overview",
        response_model=ConnectorSourceIngestionOverview,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Source ingestion read scope or tenant binding denied"},
            422: {"description": "Pagination cursor invalid"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_source_ingestion_overview(
        request: Request,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        connector_id: str = Query(default="external_db_operational_mirror", min_length=1),
        cursor: str | None = Query(default=None, min_length=1),
        limit: int = Query(default=50, ge=1, le=100),
        actor_scopes: list[str] = CheckpointActorScopesQuery,
    ) -> ConnectorSourceIngestionOverview:
        """Cross-request aggregates plus a newest-first page of requests."""
        _authorize_tenant_read(tenant_id, principal)
        _authorize_source_ingestion_read(
            principal,
            actor_scopes,
            operation="read the ingestion overview",
        )
        cursor_created_at: datetime | None = None
        cursor_request_id: str | None = None
        if cursor is not None:
            try:
                decoded = base64.urlsafe_b64decode(cursor.encode()).decode()
                if base64.urlsafe_b64encode(decoded.encode()).decode() != cursor:
                    raise ValueError("cursor is not canonical url-safe base64")
                raw_created_at, raw_request_id = decoded.split("|", 1)
                cursor_created_at = datetime.fromisoformat(raw_created_at)
                if raw_request_id == "" or "|" in raw_request_id:
                    raise ValueError("cursor request id segment is malformed")
                cursor_request_id = raw_request_id
            except (ValueError, UnicodeDecodeError, UnicodeEncodeError) as exc:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": AxisErrorCode.VALIDATION_FAILED.value,
                        "message": "That pagination cursor is not valid.",
                        "reason": "invalid_cursor",
                    },
                ) from exc
        overview = build_connector_source_ingestion_overview(
            repository,
            tenant_id=tenant_id,
            connector_id=connector_id,
            limit=limit,
            cursor_created_at=cursor_created_at,
            cursor_request_id=cursor_request_id,
            settings=request.app.state.settings,
        )
        encoded_cursor = (
            base64.urlsafe_b64encode(overview.next_cursor.encode()).decode()
            if overview.next_cursor
            else None
        )
        return overview.model_copy(update={"next_cursor": encoded_cursor})

    @operations_router.post(
        "/connectors/external-db/source-ingestion-requests",
        response_model=SourceIngestionRequestView,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Source ingestion scope or tenant binding denied"},
            409: {"description": "The request ID already names a different request"},
            422: {
                "description": (
                    "Ingestion selections are invalid, stale, inactive, "
                    "duplicate, or oversized"
                )
            },
        },
        tags=["demo"],
    )
    def manufacturing_connector_source_ingestion_request_create(
        submission: ConnectorSourceIngestionSubmission,
        request: Request,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> SourceIngestionRequestView:
        settings: Settings = request.app.state.settings
        _authorize_tenant_read(submission.tenant_id, principal)
        bound_submission = _bind_body_tenant_actor(
            submission,
            principal,
            actor_field="requested_by",
            tenant_mismatch_message=(
                "The authenticated OIDC tenant cannot request ingestion for this connector."
            ),
        )
        try:
            return record_connector_source_ingestion_request(
                repository,
                submission=bound_submission,
                principal_scopes=bound_submission.actor_scopes,
                max_selections=max_source_ingestion_selections(settings),
                settings=settings,
            )
        except SourceIngestionScopeDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": (
                        "The actor lacks the source ingestion scope required for "
                        "governed ingestion requests."
                    ),
                    "required_permission": exc.required_scope,
                    "reason": f"missing_scope:{exc.required_scope}",
                },
            ) from exc
        except ConnectorSourceIngestionError as exc:
            status_code = 409 if exc.reason == "request_id_conflict" else 422
            raise HTTPException(
                status_code=status_code,
                detail={
                    "code": (
                        AxisErrorCode.CONFLICT.value
                        if status_code == 409
                        else AxisErrorCode.VALIDATION_FAILED.value
                    ),
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.get(
        "/connectors/external-db/source-ingestion-requests",
        response_model=list[SourceIngestionRequestView],
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Source ingestion read scope or tenant binding denied"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_source_ingestion_requests_list(
        request: Request,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        connector_id: str = Query(default="external_db_operational_mirror", min_length=1),
        limit: int = Query(default=50, ge=1, le=200),
        actor_scopes: list[str] = CheckpointActorScopesQuery,
    ) -> list[SourceIngestionRequestView]:
        settings: Settings = request.app.state.settings
        _authorize_tenant_read(tenant_id, principal)
        _authorize_source_ingestion_read(
            principal,
            actor_scopes,
            operation="list ingestion requests",
        )
        return list_connector_source_ingestion_request_views(
            repository,
            tenant_id=tenant_id,
            connector_id=connector_id,
            limit=limit,
            settings=settings,
        )

    @operations_router.get(
        "/connectors/external-db/source-ingestion-requests/{request_id}",
        response_model=SourceIngestionRequestView,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Source ingestion read scope or tenant binding denied"},
            404: {"description": "Ingestion request not found"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_source_ingestion_request_status(
        request: Request,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        request_id: str,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        actor_scopes: list[str] = CheckpointActorScopesQuery,
    ) -> SourceIngestionRequestView:
        settings: Settings = request.app.state.settings
        _authorize_tenant_read(tenant_id, principal)
        _authorize_source_ingestion_read(
            principal,
            actor_scopes,
            operation="read ingestion request status",
        )
        view = get_connector_source_ingestion_request_view(
            repository,
            tenant_id=tenant_id,
            request_id=request_id,
            settings=settings,
        )
        if view is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "That ingestion request does not exist.",
                    "reason": "ingestion_request_not_found",
                },
            )
        return view

    @operations_router.post(
        "/connectors/external-db/source-ingestion-requests/{request_id}/cancel",
        response_model=SourceIngestionRequestView,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Source ingestion scope or tenant binding denied"},
            404: {"description": "Ingestion request not found"},
            409: {"description": "The request was already dispatched or is terminal"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_source_ingestion_request_cancel(
        cancel_request: ConnectorSourceIngestionCancelRequest,
        request: Request,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        request_id: str,
    ) -> SourceIngestionRequestView:
        settings: Settings = request.app.state.settings
        _authorize_tenant_read(cancel_request.tenant_id, principal)
        bound_cancel = _bind_body_tenant_actor(
            cancel_request,
            principal,
            actor_field="cancelled_by",
            tenant_mismatch_message=(
                "The authenticated OIDC tenant cannot cancel ingestion requests for "
                "this connector."
            ),
        )
        try:
            view, outcome = cancel_connector_source_ingestion_request(
                repository,
                tenant_id=bound_cancel.tenant_id,
                request_id=request_id,
                cancelled_by=bound_cancel.cancelled_by,
                cancel_reason=bound_cancel.reason or None,
                principal_scopes=bound_cancel.actor_scopes,
            )
        except SourceIngestionScopeDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": (
                        "The actor lacks the source ingestion scope required to "
                        "cancel governed ingestion requests."
                    ),
                    "required_permission": exc.required_scope,
                    "reason": f"missing_scope:{exc.required_scope}",
                },
            ) from exc
        if view is None or outcome == "not_found":
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "That ingestion request does not exist.",
                    "reason": "ingestion_request_not_found",
                },
            )
        if outcome == "conflict":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.CONFLICT.value,
                    "message": (
                        "That request can no longer be cancelled because it was "
                        "already dispatched or reached a terminal state."
                    ),
                    "reason": "cancel_conflict",
                },
            )
        return get_connector_source_ingestion_request_view(
            repository,
            tenant_id=bound_cancel.tenant_id,
            request_id=request_id,
            settings=settings,
        )

    @operations_router.post(
        "/connectors/external-db/source-ingestion-requests/{request_id}/requeue",
        response_model=SourceIngestionRequestView,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Source ingestion scope or tenant binding denied"},
            404: {"description": "Ingestion request not found"},
            409: {"description": "Only dead-lettered requests can be re-dispatched"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_source_ingestion_request_requeue(
        requeue_request: ConnectorSourceIngestionRequeueRequest,
        request: Request,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        request_id: str,
    ) -> SourceIngestionRequestView:
        _authorize_tenant_read(requeue_request.tenant_id, principal)
        bound = _bind_body_tenant_actor(
            requeue_request,
            principal,
            actor_field="requeued_by",
            tenant_mismatch_message=(
                "The authenticated OIDC tenant cannot re-dispatch ingestion requests "
                "for this connector."
            ),
        )
        try:
            _, outcome = requeue_connector_source_ingestion_request(
                repository,
                tenant_id=bound.tenant_id,
                request_id=request_id,
                requeued_by=bound.requeued_by,
                reason=bound.reason,
                idempotency_key=bound.idempotency_key,
                principal_scopes=bound.actor_scopes,
            )
        except SourceIngestionScopeDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": (
                        "The actor lacks the source ingestion scope required to "
                        "re-dispatch governed ingestion requests."
                    ),
                    "required_permission": exc.required_scope,
                    "reason": f"missing_scope:{exc.required_scope}",
                },
            ) from exc
        if outcome == "not_found":
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "That ingestion request does not exist.",
                    "reason": "ingestion_request_not_found",
                },
            )
        if outcome == "conflict":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.CONFLICT.value,
                    "message": (
                        "Only dead-lettered requests can be re-dispatched, and the "
                        "same actor, reason, and idempotency key must be repeated to "
                        "replay."
                    ),
                    "reason": "requeue_conflict",
                },
            )
        return get_connector_source_ingestion_request_view(
            repository,
            tenant_id=bound.tenant_id,
            request_id=request_id,
            settings=request.app.state.settings,
        )

    @operations_router.get(
        "/connectors/external-db/source-ingestion-requests/{request_id}/batches",
        response_model=SourceExtractionBatchesPage,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Source ingestion read scope or tenant binding denied"},
            404: {"description": "Ingestion request not found"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_source_extraction_batches(
        request: Request,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        request_id: str,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        cursor: str | None = Query(default=None, min_length=1),
        binding_id: str | None = Query(default=None, min_length=1, max_length=180),
        truncated: bool | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
        actor_scopes: list[str] = CheckpointActorScopesQuery,
    ) -> SourceExtractionBatchesPage:
        """Metadata-only extraction batches; row payloads never appear here."""
        _authorize_tenant_read(tenant_id, principal)
        _authorize_source_ingestion_read(
            principal,
            actor_scopes,
            operation="read extraction batch evidence",
        )
        cursor_key: str | None = None
        if cursor is not None:
            try:
                cursor_key = base64.urlsafe_b64decode(cursor.encode()).decode()
                if base64.urlsafe_b64encode(cursor_key.encode()).decode() != cursor:
                    raise ValueError("cursor is not canonical url-safe base64")
            except (ValueError, UnicodeDecodeError, UnicodeEncodeError) as exc:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": AxisErrorCode.VALIDATION_FAILED.value,
                        "message": "That pagination cursor is not valid.",
                        "reason": "invalid_cursor",
                    },
                ) from exc
        page = list_connector_source_extraction_batches_page(
            repository,
            tenant_id=tenant_id,
            request_id=request_id,
            limit=limit,
            cursor_key=cursor_key,
            binding_id=binding_id,
            truncated=truncated,
        )
        if page is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "That ingestion request does not exist.",
                    "reason": "ingestion_request_not_found",
                },
            )
        encoded_cursor = (
            base64.urlsafe_b64encode(page.next_cursor.encode()).decode()
            if page.next_cursor
            else None
        )
        return page.model_copy(update={"next_cursor": encoded_cursor})

    @operations_router.get(
        "/connectors/external-db/source-ingestion-requests/{request_id}/batches/reconciliation",
        response_model=SourceExtractionReconciliationReport,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Source ingestion read scope or tenant binding denied"},
            404: {"description": "Ingestion request not found"},
            409: {"description": "Dry-run refused or store adapter unsupported"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_source_extraction_reconciliation(
        request: Request,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        request_id: str,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        dry_run: bool = Query(default=True),
        actor_scopes: list[str] = CheckpointActorScopesQuery,
    ) -> SourceExtractionReconciliationReport:
        """Read-only object-store vs metadata comparison; dry-run only."""
        _authorize_tenant_read(tenant_id, principal)
        _authorize_source_ingestion_read(
            principal,
            actor_scopes,
            operation="run extraction reconciliation",
        )
        if not dry_run:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.CONFLICT.value,
                    "message": (
                        "Only dry-run reconciliation exists; repair actions are "
                        "explicitly out of scope."
                    ),
                    "reason": "dry_run_only",
                },
            )
        settings: Settings = request.app.state.settings
        # Local adapter ONLY: constructing cloud clients from an operator GET
        # would be an external effect this read-only surface must never take.
        # S3 listing support arrives as its own reviewed, wired change.
        if settings.connector_export_object_store_adapter != LOCAL_FILESYSTEM_ADAPTER:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.CONFLICT.value,
                    "message": (
                        "Reconciliation currently supports the local filesystem "
                        "object-store adapter."
                    ),
                    "reason": "store_adapter_unsupported",
                },
            )
        report = reconcile_request_batches(
            repository,
            store=LocalReconcilableObjectStore(
                StoreRootPath(settings.connector_export_object_store_root)
            ),
            local_root=StoreRootPath(settings.connector_export_object_store_root),
            tenant_id=tenant_id,
            request_id=request_id,
        )
        if report is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "That ingestion request does not exist.",
                    "reason": "ingestion_request_not_found",
                },
            )
        return report

    def _map_batch_export_error(exc: ConnectorSourceBatchExportError) -> HTTPException:
        """One public-safe mapping for every batch-envelope export failure."""
        not_found_reasons = {
            "batch_export_request_not_found",
            "ingestion_request_not_found",
        }
        conflict_reasons = {
            "idempotency_conflict",
            "export_request_id_already_exists",
            "batch_envelope_too_large",
            "decision_conflict",
            "export_request_not_approved",
            "export_request_already_materialized",
            "materialization_idempotency_conflict",
            "envelope_checksum_changed",
            "artifact_not_written",
            "store_adapter_unsupported",
            "artifact_checksum_mismatch",
            "artifact_key_unsafe",
            "artifact_unreadable",
            "artifact_unparseable",
        }
        if exc.reason in not_found_reasons:
            return HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            )
        if exc.reason in conflict_reasons:
            return HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.CONFLICT.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            )
        return HTTPException(
            status_code=422,
            detail={
                "code": AxisErrorCode.VALIDATION_FAILED.value,
                "message": exc.message,
                "reason": exc.reason,
            },
        )

    @operations_router.post(
        "/connectors/external-db/source-ingestion-requests/{request_id}/"
        "batch-envelope-export-requests",
        response_model=ConnectorSourceBatchExportRequestRecord,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Batch export request scope denied"},
            404: {"description": "Ingestion request not found"},
            409: {"description": "Idempotency or export request ID conflict"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_source_batch_export_request_create(
        export_request: ConnectorSourceBatchExportRequestInput,
        request: Request,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        request_id: str,
    ) -> Response:
        _authorize_tenant_read(export_request.tenant_id, principal)
        bound = _bind_body_tenant_actor(
            export_request,
            principal,
            actor_field="requested_by",
            tenant_mismatch_message=(
                "The authenticated OIDC tenant cannot request batch-envelope "
                "exports for this connector."
            ),
        )
        if bound.request_id != request_id:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "The body and URL must name the same request.",
                    "reason": "request_path_mismatch",
                },
            )
        try:
            record = record_connector_source_batch_export_request(
                repository,
                request=bound,
            )
        except ConnectorSourceBatchExportScopeDenied as exc:
            required = exc.required_scope
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": (
                        "The actor lacks the scope required to request "
                        "batch-envelope exports."
                    ),
                    "required_permission": required,
                    "reason": f"missing_scope:{required}",
                },
            ) from exc
        except ConnectorSourceBatchExportError as exc:
            raise _map_batch_export_error(exc) from exc
        status_code = 200 if record.idempotent_replay else 201
        return JSONResponse(
            status_code=status_code,
            content=record.model_dump(mode="json"),
        )

    @operations_router.post(
        "/connectors/external-db/source-ingestion-requests/{request_id}/"
        "batch-envelope-export-requests/{export_request_id}/decision",
        response_model=ConnectorSourceBatchExportDecisionResult,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Export decision scope denied"},
            404: {"description": "Export request not found"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_source_batch_export_decision(
        decision_input: ConnectorSourceBatchExportDecisionInput,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        request_id: str,
        export_request_id: str,
    ) -> ConnectorSourceBatchExportDecisionResult:
        _authorize_tenant_read(decision_input.tenant_id, principal)
        bound = _bind_body_tenant_actor(
            decision_input,
            principal,
            actor_field="actor_id",
            tenant_mismatch_message=(
                "The authenticated OIDC tenant cannot decide batch-envelope "
                "export requests for this tenant."
            ),
        )
        try:
            return decide_connector_source_batch_export_request(
                repository,
                request_id=request_id,
                export_request_id=export_request_id,
                decision_input=bound,
            )
        except ConnectorSourceBatchExportScopeDenied as exc:
            required = exc.required_scope
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": (
                        "The actor lacks the scope required to decide "
                        "batch-envelope export requests."
                    ),
                    "required_permission": required,
                    "reason": f"missing_scope:{required}",
                },
            ) from exc
        except ConnectorSourceBatchExportError as exc:
            raise _map_batch_export_error(exc) from exc

    @operations_router.post(
        "/connectors/external-db/source-ingestion-requests/{request_id}/"
        "batch-envelope-export-requests/{export_request_id}/materializations",
        response_model=ConnectorSourceBatchExportMaterializationResult,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Materialization scope denied"},
            404: {"description": "Export request not found"},
            409: {"description": "Approval gate, checksum drift or replay conflict"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_source_batch_export_materialization(
        materialization_input: ConnectorSourceBatchExportMaterializationInput,
        request: Request,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        request_id: str,
        export_request_id: str,
    ) -> ConnectorSourceBatchExportMaterializationResult:
        settings: Settings = request.app.state.settings
        # Adapter guard BEFORE any object-store construction: this route must
        # never build a cloud client as a side effect of an operator POST. The
        # local store below is constructed only for the supported adapter.
        if settings.connector_export_object_store_adapter != LOCAL_FILESYSTEM_ADAPTER:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.CONFLICT.value,
                    "message": (
                        "Batch-envelope materialization currently supports only "
                        "the local filesystem object-store adapter."
                    ),
                    "reason": "store_adapter_unsupported",
                },
            )
        _authorize_tenant_read(
            materialization_input.tenant_id, principal
        )
        bound = _bind_body_tenant_actor(
            materialization_input,
            principal,
            actor_field="actor_id",
            tenant_mismatch_message=(
                "The authenticated OIDC tenant cannot materialize batch-envelope "
                "exports for this tenant."
            ),
        )
        try:
            result = materialize_connector_source_batch_export_request(
                repository,
                object_store=LocalObjectStore(
                    settings.connector_export_object_store_root
                ),
                request_id=request_id,
                export_request_id=export_request_id,
                materialization_input=bound,
            )
        except ConnectorSourceBatchExportScopeDenied as exc:
            required = exc.required_scope
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": (
                        "The actor lacks the scope required to materialize "
                        "batch-envelope exports."
                    ),
                    "required_permission": required,
                    "reason": f"missing_scope:{required}",
                },
            ) from exc
        except ConnectorSourceBatchExportError as exc:
            raise _map_batch_export_error(exc) from exc
        # Fresh single-shot writes are 201; exact replays return the canonical
        # stored truth as 200 — mirroring the evidence-snapshot export route.
        return JSONResponse(
            status_code=200 if result.idempotent_replay else 201,
            content=result.model_dump(mode="json"),
        )

    @operations_router.get(
        "/connectors/external-db/source-ingestion-requests/{request_id}/"
        "batch-envelope-export-requests/{export_request_id}/artifact",
        responses={
            200: {"content": {"application/json": {}}},
            401: {"description": "OIDC authentication required"},
            403: {"description": "Source ingestion read scope or tenant binding denied"},
            404: {"description": "Export request not found"},
            409: {"description": "Artifact missing, checksum mismatch, or adapter unsupported"},
        },
        tags=["demo"],
    )
    def manufacturing_connector_source_batch_export_artifact(
        request: Request,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        request_id: str,
        export_request_id: str,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        actor_scopes: list[str] = CheckpointActorScopesQuery,
    ) -> Response:
        """Checksum-verified artifact download; LOCAL adapter only."""
        settings: Settings = request.app.state.settings
        _authorize_tenant_read(tenant_id, principal)
        _authorize_source_ingestion_read(
            principal,
            actor_scopes,
            operation="retrieve batch-envelope artifacts",
        )
        actor_id = principal.actor_id if principal is not None else "console-operator"
        # Adapter guard FIRST: a non-local deployment must receive its precise
        # 409 without any reader construction, client creation, or egress.
        if settings.connector_export_object_store_adapter != LOCAL_FILESYSTEM_ADAPTER:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.CONFLICT.value,
                    "message": (
                        "Artifact retrieval supports only the local filesystem "
                        "object-store adapter."
                    ),
                    "reason": "store_adapter_unsupported",
                },
            )
        try:
            bundle, record, raw = read_connector_source_batch_export_artifact(
                repository,
                reader=LocalBatchExportArtifactReader(
                    StoreRootPath(settings.connector_export_object_store_root)
                ),
                tenant_id=tenant_id,
                request_id=request_id,
                export_request_id=export_request_id,
                actor_id=actor_id,
            )
        except ConnectorSourceBatchExportError as exc:
            raise _map_batch_export_error(exc) from exc
        if bundle.manifest.get("envelope_checksum_sha256") != (
            record.envelope_checksum_sha256
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.CONFLICT.value,
                    "message": (
                        "The stored artifact manifest does not match the export "
                        "request."
                    ),
                    "reason": "artifact_checksum_mismatch",
                },
            )
        return Response(
            content=raw,
            media_type=record.artifact_content_type or "application/json",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{export_request_id}.json"'
                ),
            },
        )

    @app.get(
        "/platform/policies",
        response_model=PlatformPolicyRegistry,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Platform policy read permission denied"},
        },
        tags=["platform"],
    )
    def platform_policy_registry(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        scope: PlatformPolicyScope | None = PlatformPolicyScopeQuery,
        status_filter: str | None = Query(default=None, alias="status", min_length=1),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> PlatformPolicyRegistry:
        _authorize_platform_policy_read(
            tenant_id=tenant_id,
            principal=principal,
            resource="platform_policies",
        )
        query = PlatformPolicyQuery(
            tenant_id=tenant_id,
            scope=scope,
            status=status_filter,
            limit=limit,
        )
        return build_platform_policy_registry(
            repository,
            tenant_id=query.tenant_id,
            scope=query.scope,
            status=query.status,
            limit=query.limit,
        )

    @app.post(
        "/platform/policies",
        response_model=PlatformPolicyRecord,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Platform policy authoring permission denied"},
            409: {"description": "Platform policy already exists"},
            422: {"description": "Platform policy validation failed"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["platform"],
    )
    def platform_policy_create(
        policy_request: PlatformPolicyCreateRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> PlatformPolicyRecord:
        try:
            bound_policy = _bind_body_tenant_actor(policy_request, principal, "created_by")
            return record_platform_policy(repository, bound_policy)
        except PlatformPolicyPermissionDenied as exc:
            reason = (
                "missing_required_scope"
                if exc.decision.reason.startswith("missing_scope:")
                else exc.decision.reason
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot author platform policies.",
                    "required_permission": exc.required_permission,
                    "reason": reason,
                    "permission_reason": exc.decision.reason,
                },
            ) from exc
        except PlatformPolicyConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.POLICY_VIOLATION.value,
                    "message": "The platform policy already exists.",
                    "reason": "policy_already_exists",
                    "policy_id": exc.policy_id,
                },
            ) from exc
        except PlatformPolicyValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @app.get(
        "/platform/policies/{policy_id}",
        response_model=PlatformPolicyDetail,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Platform policy read permission denied"},
            404: {"description": "Platform policy not found"},
        },
        tags=["platform"],
    )
    def platform_policy_detail(
        policy_id: str,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
    ) -> PlatformPolicyDetail:
        _authorize_platform_policy_read(
            tenant_id=tenant_id,
            principal=principal,
            resource="platform_policy_detail",
        )
        try:
            return get_platform_policy_detail(repository, tenant_id, policy_id)
        except PlatformPolicyNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "The platform policy was not found for this tenant.",
                    "policy_id": policy_id,
                },
            ) from exc

    @app.post(
        "/platform/policies/{policy_id}/revisions",
        response_model=PlatformPolicyRecord,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Platform policy revision permission denied"},
            404: {"description": "Platform policy not found"},
            409: {"description": "Platform policy revision idempotency conflict"},
            422: {"description": "Platform policy revision validation failed"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["platform"],
    )
    def platform_policy_revise(
        policy_id: str,
        revise_request: PlatformPolicyReviseRequest,
        response: Response,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> PlatformPolicyRecord:
        if policy_id != revise_request.policy_id:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "The path policy_id must match the request policy_id.",
                    "reason": "policy_id_mismatch",
                },
            )
        try:
            bound_request = _bind_body_tenant_actor(revise_request, principal, "updated_by")
            result = revise_platform_policy(repository, bound_request)
        except PlatformPolicyNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "The platform policy was not found for this tenant.",
                    "policy_id": policy_id,
                },
            ) from exc
        except PlatformPolicyPermissionDenied as exc:
            reason = (
                "missing_required_scope"
                if exc.decision.reason.startswith("missing_scope:")
                else exc.decision.reason
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot revise platform policies.",
                    "required_permission": exc.required_permission,
                    "reason": reason,
                    "permission_reason": exc.decision.reason,
                },
            ) from exc
        except PlatformPolicyRevisionConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.POLICY_VIOLATION.value,
                    "message": (
                        "The revision idempotency key already exists with a different payload."
                    ),
                    "reason": "revision_idempotency_conflict",
                    "policy_id": exc.policy_id,
                },
            ) from exc
        except PlatformPolicyValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

        if result.idempotent_replay:
            response.status_code = status.HTTP_200_OK
        return result

    @app.post(
        "/platform/policies/evaluate",
        response_model=PlatformPolicyDecision,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Platform policy evaluation permission denied"},
        },
        tags=["platform"],
    )
    def platform_policy_evaluate(
        evaluation_request: PlatformPolicyEvaluationRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> PlatformPolicyDecision:
        try:
            bound_request = _bind_body_tenant_actor(evaluation_request, principal, "actor_id")
            return evaluate_platform_policy_request(repository, bound_request)
        except PlatformPolicyPermissionDenied as exc:
            reason = (
                "missing_required_scope"
                if exc.decision.reason.startswith("missing_scope:")
                else exc.decision.reason
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot evaluate platform policies.",
                    "required_permission": exc.required_permission,
                    "reason": reason,
                    "permission_reason": exc.decision.reason,
                },
            ) from exc

    @app.post(
        "/platform/tenants",
        response_model=TenantRecord,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Platform tenant provisioning permission denied"},
            409: {"description": "Tenant provisioning conflict"},
            422: {"description": "Tenant provisioning validation failed"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["platform"],
    )
    def platform_tenant_provision(
        provision_request: TenantProvisionRequest,
        response: Response,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> TenantRecord:
        try:
            bound_request = _bind_platform_tenant_actor(provision_request, principal)
            result = provision_tenant(repository, bound_request)
        except TenantPermissionDenied as exc:
            raise _platform_tenant_denied_http_exception(
                exc,
                "The actor cannot provision tenants.",
            ) from exc
        except TenantProvisionConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.CONFLICT.value,
                    "message": "The tenant provisioning request conflicts with persisted state.",
                    "reason": exc.reason,
                    "tenant_id": exc.tenant_id,
                },
            ) from exc

        if result.idempotent_replay:
            response.status_code = status.HTTP_200_OK
        repository.defer_until_after_commit(
            lambda: app.state.tenant_state_cache.invalidate(result.tenant_id)
        )
        return result

    @app.get(
        "/platform/tenants",
        response_model=TenantRegistry,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Platform tenant read permission denied"},
            422: {"description": "Tenant listing cursor is invalid"},
        },
        tags=["platform"],
    )
    def platform_tenant_registry(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        status_filter: TenantLifecycleStatus | None = TenantLifecycleStatusQuery,
        limit: int = Query(default=100, ge=1, le=200),
        cursor: str | None = Query(default=None, min_length=1, max_length=600),
    ) -> TenantRegistry:
        _authorize_platform_tenant_read(principal, resource="platform_tenants")
        try:
            cursor_tenant_id = decode_tenant_cursor(cursor)
        except TenantListCursorError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "The tenant listing cursor is invalid.",
                    "reason": exc.reason,
                },
            ) from exc
        return build_tenant_registry(
            repository,
            status=status_filter,
            limit=limit,
            cursor_tenant_id=cursor_tenant_id,
        )

    @app.get(
        "/platform/tenants/{tenant_id}",
        response_model=TenantRecord,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Platform tenant read permission denied"},
            404: {"description": "Tenant not found"},
        },
        tags=["platform"],
    )
    def platform_tenant_detail(
        tenant_id: str,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> TenantRecord:
        _authorize_platform_tenant_read(principal, resource="platform_tenant")
        try:
            return get_tenant_detail(repository, tenant_id)
        except TenantNotFound as exc:
            raise _platform_tenant_not_found_http_exception(tenant_id) from exc

    @app.post(
        "/platform/tenants/{tenant_id}/suspend",
        response_model=TenantRecord,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Platform tenant suspend permission denied"},
            404: {"description": "Tenant not found"},
            409: {"description": "Tenant lifecycle conflict"},
        },
        tags=["platform"],
    )
    def platform_tenant_suspend(
        tenant_id: str,
        suspend_request: TenantSuspendRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> TenantRecord:
        try:
            bound_request = _bind_platform_tenant_actor(suspend_request, principal)
            result = suspend_tenant(repository, tenant_id, bound_request)
        except TenantNotFound as exc:
            raise _platform_tenant_not_found_http_exception(tenant_id) from exc
        except TenantPermissionDenied as exc:
            raise _platform_tenant_denied_http_exception(
                exc,
                "The actor cannot suspend tenants.",
            ) from exc
        except TenantLifecycleConflict as exc:
            raise _platform_tenant_lifecycle_conflict_http_exception(exc) from exc

        repository.defer_until_after_commit(
            lambda: app.state.tenant_state_cache.invalidate(tenant_id)
        )
        return result

    @app.post(
        "/platform/tenants/{tenant_id}/reactivate",
        response_model=TenantRecord,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Platform tenant reactivate permission denied"},
            404: {"description": "Tenant not found"},
            409: {"description": "Tenant lifecycle conflict"},
        },
        tags=["platform"],
    )
    def platform_tenant_reactivate(
        tenant_id: str,
        reactivate_request: TenantReactivateRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> TenantRecord:
        try:
            bound_request = _bind_platform_tenant_actor(reactivate_request, principal)
            result = reactivate_tenant(repository, tenant_id, bound_request)
        except TenantNotFound as exc:
            raise _platform_tenant_not_found_http_exception(tenant_id) from exc
        except TenantPermissionDenied as exc:
            raise _platform_tenant_denied_http_exception(
                exc,
                "The actor cannot reactivate tenants.",
            ) from exc
        except TenantLifecycleConflict as exc:
            raise _platform_tenant_lifecycle_conflict_http_exception(exc) from exc

        repository.defer_until_after_commit(
            lambda: app.state.tenant_state_cache.invalidate(tenant_id)
        )
        return result

    @app.get(
        "/platform/tenants/{tenant_id}/quotas",
        response_model=TenantQuotaSet,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Platform tenant read permission denied"},
            404: {"description": "Tenant not found"},
        },
        tags=["platform"],
    )
    def platform_tenant_quotas(
        tenant_id: str,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> TenantQuotaSet:
        _authorize_platform_tenant_read(principal, resource="platform_tenant_quotas")
        try:
            return get_tenant_quota_set(repository, tenant_id)
        except TenantNotFound as exc:
            raise _platform_tenant_not_found_http_exception(tenant_id) from exc

    @app.get(
        "/platform/tenants/{tenant_id}/vocabulary",
        response_model=TenantVocabularySet,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Platform tenant read permission denied"},
            404: {"description": "Tenant not found"},
        },
        tags=["platform"],
    )
    def platform_tenant_vocabulary(
        tenant_id: str,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> TenantVocabularySet:
        _authorize_platform_tenant_read(
            principal,
            resource="platform_tenant_vocabulary",
        )
        try:
            return get_tenant_vocabulary(repository, tenant_id)
        except TenantNotFound as exc:
            raise _platform_tenant_not_found_http_exception(tenant_id) from exc

    @app.get(
        "/platform/tenants/{tenant_id}/usage",
        response_model=TenantUsageSummary,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Platform tenant usage read permission denied"},
            404: {"description": "Tenant not found"},
            422: {"description": "Usage window is invalid"},
        },
        tags=["platform"],
    )
    def platform_tenant_usage(
        tenant_id: str,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        last_days: int = TenantUsageLastDaysQuery,
        from_: datetime | None = TenantUsageFromQuery,
        to: datetime | None = TenantUsageToQuery,
    ) -> TenantUsageSummary:
        _authorize_platform_tenant_usage_read(principal, resource="platform_tenant_usage")
        # Normalize mixed naive/aware inputs to UTC so a naive from/to compared
        # against an aware now() yields a clean 422, not a TypeError-driven 500.
        window_end = ensure_aware_datetime(to) if to is not None else datetime.now(UTC)
        window_start = (
            ensure_aware_datetime(from_)
            if from_ is not None
            else window_end - timedelta(days=last_days)
        )
        if window_start >= window_end:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "The usage window start must be before the window end.",
                    "reason": "invalid_usage_window",
                },
            )
        try:
            return build_tenant_usage_summary(
                repository,
                tenant_id,
                window_start=window_start,
                window_end=window_end,
                window_seconds=(resolved_settings.usage_metering_aggregation_window_seconds),
            )
        except TenantNotFound as exc:
            raise _platform_tenant_not_found_http_exception(tenant_id) from exc

    @app.put(
        "/platform/tenants/{tenant_id}/quotas",
        response_model=TenantQuotaSet,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Platform tenant quota permission denied"},
            404: {"description": "Tenant not found"},
            422: {"description": "Tenant quota validation failed"},
        },
        tags=["platform"],
    )
    def platform_tenant_quotas_update(
        tenant_id: str,
        quota_request: TenantQuotaUpdateRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> TenantQuotaSet:
        try:
            bound_request = _bind_platform_tenant_actor(quota_request, principal)
            result = update_tenant_quotas(repository, tenant_id, bound_request)
        except TenantNotFound as exc:
            raise _platform_tenant_not_found_http_exception(tenant_id) from exc
        except TenantPermissionDenied as exc:
            raise _platform_tenant_denied_http_exception(
                exc,
                "The actor cannot update tenant quotas.",
            ) from exc

        repository.defer_until_after_commit(
            lambda: app.state.tenant_state_cache.invalidate(tenant_id)
        )
        return result

    @app.put(
        "/platform/tenants/{tenant_id}/vocabulary",
        response_model=TenantVocabularySet,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Platform tenant configure permission denied"},
            404: {"description": "Tenant not found"},
            422: {"description": "Tenant vocabulary validation failed"},
        },
        tags=["platform"],
    )
    def platform_tenant_vocabulary_update(
        tenant_id: str,
        vocabulary_request: TenantVocabularyUpdateRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> TenantVocabularySet:
        try:
            bound_request = _bind_platform_tenant_actor(vocabulary_request, principal)
            return update_tenant_vocabulary(repository, tenant_id, bound_request)
        except TenantNotFound as exc:
            raise _platform_tenant_not_found_http_exception(tenant_id) from exc
        except TenantPermissionDenied as exc:
            raise _platform_tenant_denied_http_exception(
                exc,
                "The actor cannot update tenant vocabulary.",
            ) from exc

    @operations_router.get(
        "/actions/runs",
        response_model=ActionRunList,
        responses={403: {"description": "Action run read permission denied"}},
        tags=["demo"],
    )
    def manufacturing_action_run_list(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        action_id: str | None = Query(default=None, min_length=1),
        status: str | None = Query(default=None, min_length=1),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> ActionRunList:
        _authorize_tenant_read(tenant_id, principal)
        return list_action_run_records(
            repository,
            ActionRunQuery(
                tenant_id=tenant_id,
                action_id=action_id,
                status=status,
                limit=limit,
            ),
        )

    @operations_router.post(
        "/actions/{action_id}/runs",
        response_model=ActionRunPersistenceResult,
        responses={
            404: {
                "description": (
                    "Action, action registry reference, or ontology reference record not found"
                )
            },
            403: {"description": "Action run permission denied"},
            409: {"description": "Action run idempotency conflict"},
            422: {
                "description": (
                    "Action payload, action registry reference, or ontology reference invalid"
                )
            },
        },
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    async def manufacturing_action_run(
        action_id: str,
        action_run: ActionRunRequest,
        repository: PersistenceRepository,
        runtime: WorkflowRuntime,
        principal: OidcPrincipalDependency,
        response: Response,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
    ) -> ActionRunPersistenceResult:
        with telemetry.tracer.start_as_current_span("axis.action_run.create") as span:
            set_span_attributes(
                span,
                {
                    ATTR_ACTION_ID: action_id,
                    ATTR_TENANT_ID: tenant_id,
                    ATTR_ACTOR_ID: principal.actor_id if principal else None,
                },
            )
            try:
                bound_action_run = _bind_tenant_actor(action_run, principal, tenant_id)
                result = await record_demo_action_run(
                    repository,
                    action_id,
                    bound_action_run,
                    runtime,
                    tenant_id=tenant_id,
                    workflow_history_persistence_enabled=(
                        resolved_settings.workflow_history_persistence_enabled
                    ),
                )
            except DemoActionNotFound as exc:
                raise HTTPException(status_code=404, detail="Action not found") from exc
            except ActionReferenceRecordNotFound as exc:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": AxisErrorCode.NOT_FOUND.value,
                        "message": "Manufacturing action registry reference record not found.",
                        "surface": "actions",
                    },
                ) from exc
            except ActionReferenceRecordInvalid as exc:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": AxisErrorCode.VALIDATION_FAILED.value,
                        "message": "Manufacturing action registry reference payload is invalid.",
                        "surface": "actions",
                    },
                ) from exc
            except OntologyReferenceRecordNotFound as exc:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": AxisErrorCode.NOT_FOUND.value,
                        "message": "Manufacturing ontology reference record not found.",
                        "surface": "ontology",
                    },
                ) from exc
            except OntologyReferenceRecordInvalid as exc:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": AxisErrorCode.VALIDATION_FAILED.value,
                        "message": "Manufacturing ontology reference payload is invalid.",
                        "surface": "ontology",
                    },
                ) from exc
            except ActionPermissionDenied as exc:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": AxisErrorCode.PERMISSION_DENIED.value,
                        "message": "The actor cannot request this action run.",
                        "required_permissions": exc.required_permissions,
                        "reason": exc.decision.reason,
                    },
                ) from exc
            except PlatformPolicyEnforcementDenied as exc:
                repository.session.commit()
                raise HTTPException(
                    status_code=403,
                    detail=_platform_policy_denied_detail(
                        exc,
                        "A platform policy denies this action run.",
                    ),
                ) from exc
            except ActionRunIdempotencyConflict as exc:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": AxisErrorCode.POLICY_VIOLATION.value,
                        "message": "The idempotency key already exists with a different payload.",
                        "action_run_id": str(exc.action_run_id),
                    },
                ) from exc
            except ActionPayloadValidationError as exc:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": AxisErrorCode.VALIDATION_FAILED.value,
                        "message": "The action payload does not match the typed input schema.",
                        "issues": exc.issues,
                    },
                ) from exc

            outcome = "idempotent_replay" if result.idempotent_replay else "recorded"
            set_span_attributes(span, {ATTR_OUTCOME: outcome})
            telemetry.action_run_counter.add(1, {"outcome": outcome})
            if result.idempotent_replay:
                response.status_code = status.HTTP_200_OK

            return result

    @operations_router.post(
        "/actions/runs/{action_run_id}/outcome",
        response_model=ActionRunOutcomePersistenceResult,
        responses={
            403: {"description": "Action run outcome permission denied"},
            404: {"description": "Action run not found"},
            409: {"description": "Action run outcome idempotency conflict"},
            422: {"description": "Action run outcome validation failed"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    async def manufacturing_action_run_outcome(
        action_run_id: UUID,
        outcome: ActionRunOutcomeRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        response: Response,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
    ) -> ActionRunOutcomePersistenceResult:
        try:
            bound_outcome = _bind_tenant_actor(outcome, principal, tenant_id)
            result = await record_demo_action_run_outcome(
                repository,
                action_run_id,
                bound_outcome,
                tenant_id=tenant_id,
                workflow_history_persistence_enabled=(
                    resolved_settings.workflow_history_persistence_enabled
                ),
            )
        except DemoActionRunNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "Action run not found.",
                    "surface": "actions",
                },
            ) from exc
        except ActionRunOutcomePermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot record this action run outcome.",
                    "required_permission": exc.required_permission,
                    "reason": exc.decision.reason,
                },
            ) from exc
        except PlatformPolicyEnforcementDenied as exc:
            repository.session.commit()
            raise HTTPException(
                status_code=403,
                detail=_platform_policy_denied_detail(
                    exc,
                    "A platform policy denies this action run outcome.",
                ),
            ) from exc
        except ActionRunOutcomeConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.POLICY_VIOLATION.value,
                    "message": "The action run outcome conflicts with existing evidence.",
                    "reason": exc.reason,
                    "action_run_id": str(exc.action_run_id),
                },
            ) from exc
        except ActionRunOutcomeValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "The action run outcome cannot be recorded.",
                    "issues": exc.issues,
                },
            ) from exc

        if result.idempotent_replay:
            response.status_code = status.HTTP_200_OK

        return result

    @operations_router.get(
        "/approvals",
        response_model=ManufacturingApprovalInbox,
        responses={
            404: {"description": "Approval inbox reference record not found"},
            422: {"description": "Approval inbox reference payload invalid"},
        },
        tags=["demo"],
    )
    def manufacturing_approval_inbox(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(min_length=1),
    ) -> ManufacturingApprovalInbox:
        _authorize_tenant_read(tenant_id, principal)
        try:
            return get_persisted_manufacturing_approval_inbox(
                repository,
                tenant_id=tenant_id,
            )
        except ApprovalReferenceRecordNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "Manufacturing approval inbox reference record not found.",
                    "tenant_id": tenant_id,
                    "surface": "approvals",
                },
            ) from exc
        except ApprovalReferenceRecordInvalid as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "Manufacturing approval inbox reference payload is invalid.",
                    "tenant_id": tenant_id,
                    "surface": "approvals",
                },
            ) from exc

    @operations_router.post(
        "/approvals/{approval_id}/decision",
        response_model=ApprovalDecisionPersistenceResult,
        responses={
            403: {"description": "Approval decision permission denied"},
            409: {"description": "Approval terminal decision conflict or replay unavailable"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    async def manufacturing_approval_decision(
        approval_id: str,
        decision: ApprovalDecisionRequest,
        response: Response,
        repository: PersistenceRepository,
        runtime: WorkflowRuntime,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
    ) -> ApprovalDecisionPersistenceResult:
        with telemetry.tracer.start_as_current_span("axis.approval.decide") as span:
            set_span_attributes(
                span,
                {
                    ATTR_APPROVAL_ID: approval_id,
                    ATTR_DECISION: getattr(decision.decision, "value", None),
                    ATTR_TENANT_ID: tenant_id,
                    ATTR_ACTOR_ID: principal.actor_id if principal else None,
                },
            )
            try:
                bound_decision = _bind_tenant_actor(decision, principal, tenant_id)
                result = await record_demo_approval_decision(
                    repository,
                    approval_id,
                    bound_decision,
                    runtime,
                    tenant_id=tenant_id,
                    workflow_history_persistence_enabled=(
                        resolved_settings.workflow_history_persistence_enabled
                    ),
                    workflow_signal_outbox_enabled=(
                        resolved_settings.approval_decision_outbox_enabled
                    ),
                )
                if result.idempotent_replay:
                    response.status_code = status.HTTP_200_OK
                telemetry.approval_decision_counter.add(
                    1, {"decision": getattr(decision.decision, "value", "unknown")}
                )
                return result
            except DemoApprovalNotFound as exc:
                raise HTTPException(status_code=404, detail="Approval not found") from exc
            except ApprovalReferenceRecordNotFound as exc:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": AxisErrorCode.NOT_FOUND.value,
                        "message": "Manufacturing approval inbox reference record not found.",
                        "surface": "approvals",
                    },
                ) from exc
            except ApprovalReferenceRecordInvalid as exc:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": AxisErrorCode.VALIDATION_FAILED.value,
                        "message": "Manufacturing approval inbox reference payload is invalid.",
                        "surface": "approvals",
                    },
                ) from exc
            except ApprovalPermissionDenied as exc:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": AxisErrorCode.PERMISSION_DENIED.value,
                        "message": "The actor cannot decide this approval.",
                        "required_permission": exc.required_permission,
                        "reason": exc.decision.reason,
                    },
                ) from exc
            except ApprovalDecisionConflict as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": AxisErrorCode.CONFLICT.value,
                        "message": "The approval already has a terminal decision.",
                        "approval_id": exc.approval_id,
                        "reason": exc.reason,
                    },
                ) from exc
            except PlatformPolicyEnforcementDenied as exc:
                repository.session.commit()
                raise HTTPException(
                    status_code=403,
                    detail=_platform_policy_denied_detail(
                        exc,
                        "A platform policy denies approving this action.",
                    ),
                ) from exc

    @operations_router.get(
        "/approvals/{approval_id}/decision-delivery",
        response_model=ApprovalDecisionDeliveryStatus,
        responses={404: {"description": "Approval decision delivery record not found"}},
        tags=["demo"],
    )
    def manufacturing_approval_decision_delivery(
        approval_id: str,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
    ) -> ApprovalDecisionDeliveryStatus:
        _authorize_tenant_read(tenant_id, principal)
        delivery = get_approval_decision_delivery_status(
            repository,
            tenant_id=tenant_id,
            approval_id=approval_id,
        )
        if delivery is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "Approval decision delivery record not found.",
                    "approval_id": approval_id,
                },
            )
        return delivery

    @operations_router.get(
        "/audit",
        response_model=ManufacturingAuditExplorer,
        responses={
            404: {"description": "Audit explorer reference record not found"},
            422: {"description": "Audit explorer reference payload invalid"},
        },
        tags=["demo"],
    )
    def manufacturing_audit_explorer(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(min_length=1),
    ) -> ManufacturingAuditExplorer:
        _authorize_tenant_read(tenant_id, principal)
        try:
            return get_persisted_manufacturing_audit_explorer(
                repository,
                tenant_id=tenant_id,
            )
        except AuditReferenceRecordNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "Manufacturing audit explorer reference record not found.",
                    "tenant_id": tenant_id,
                    "surface": "audit",
                },
            ) from exc
        except AuditReferenceRecordInvalid as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "Manufacturing audit explorer reference payload is invalid.",
                    "tenant_id": tenant_id,
                    "surface": "audit",
                },
            ) from exc

    @operations_router.get(
        "/audit/events",
        response_model=ManufacturingAuditExplorer,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Audit read permission denied"},
        },
        tags=["demo"],
    )
    def manufacturing_persisted_audit_events(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(min_length=1),
        event_type: str | None = Query(default=None, min_length=1),
        actor_id: str | None = Query(default=None, min_length=1),
        scope: str | None = Query(default=None, min_length=1),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> ManufacturingAuditExplorer:
        _authorize_audit_scope(
            tenant_id=tenant_id,
            principal=principal,
            required_scope=AUDIT_READ_SCOPE,
            message="The actor cannot read persisted audit events.",
            resource="audit_events",
        )
        return query_persisted_audit_events(
            repository,
            AuditEventQuery(
                tenant_id=tenant_id,
                event_type=event_type,
                actor_id=actor_id,
                scope=scope,
                limit=limit,
            ),
        )

    @operations_router.get(
        "/audit/export",
        response_model=AuditExportBundle,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Audit export permission denied"},
        },
        tags=["demo"],
    )
    def manufacturing_persisted_audit_export(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        event_type: str | None = Query(default=None, min_length=1),
        actor_id: str | None = Query(default=None, min_length=1),
        scope: str | None = Query(default=None, min_length=1),
        limit: int = Query(default=100, ge=1, le=200),
        export_reason: str = Query(default="governance-review", min_length=1, max_length=120),
        retention_days: int = Query(default=365, ge=30, le=3650),
        legal_hold: bool = Query(default=False),
        format: str = Query(default="json", pattern="^json$"),
    ) -> AuditExportBundle:
        _authorize_audit_scope(
            tenant_id=tenant_id,
            principal=principal,
            required_scope=AUDIT_READ_SCOPE,
            message="The actor cannot export persisted audit events.",
            resource="audit_export",
        )
        require_worm_compliance = _audit_export_worm_settings(app.state.settings)
        object_lock_capability = (
            _audit_export_object_lock_capability(app) if require_worm_compliance else None
        )
        try:
            with telemetry.tracer.start_as_current_span("axis.audit.export") as span:
                set_span_attributes(
                    span,
                    {
                        ATTR_TENANT_ID: tenant_id,
                        ATTR_EXPORT_FORMAT: format,
                        ATTR_ACTOR_ID: principal.actor_id if principal else None,
                    },
                )
                bundle = export_persisted_audit_events(
                    repository,
                    AuditExportQuery(
                        tenant_id=tenant_id,
                        event_type=event_type,
                        actor_id=actor_id,
                        scope=scope,
                        limit=limit,
                        export_reason=export_reason,
                        retention_days=retention_days,
                        legal_hold=legal_hold,
                        format=format,
                    ),
                    ledger_signer=_audit_ledger_signer_from_settings(app.state.settings),
                    object_lock_capability=object_lock_capability,
                    require_worm_compliance=require_worm_compliance,
                )
                telemetry.audit_export_counter.add(1, {"format": format})
                return bundle
        except AuditExportWormEnforcementError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": AxisErrorCode.CONNECTOR_UNAVAILABLE.value,
                    "message": (
                        "COMPLIANCE audit export refused: the backing object "
                        "store cannot enforce WORM object-lock."
                    ),
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.post(
        "/audit/retention/delete",
        response_model=AuditRetentionDeletionResult,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Audit retention deletion permission denied"},
        },
        tags=["demo"],
    )
    def manufacturing_audit_retention_delete(
        deletion_request: AuditRetentionDeletionRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> AuditRetentionDeletionResult:
        try:
            return execute_audit_retention_deletion(
                repository,
                _bind_audit_actor(deletion_request, principal),
            )
        except AuditRetentionDeletionPermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot execute audit retention deletion.",
                    "required_permissions": [RETENTION_DELETION_REQUIRED_SCOPE],
                    "reason": exc.decision.reason,
                },
            ) from exc

    @operations_router.get(
        "/audit/legal-holds",
        response_model=list[AuditLegalHoldRecord],
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Audit legal hold permission denied"},
        },
        tags=["demo"],
    )
    def manufacturing_audit_legal_holds(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
    ) -> list[AuditLegalHoldRecord]:
        _authorize_audit_scope(
            tenant_id=tenant_id,
            principal=principal,
            required_scope=LEGAL_HOLD_REQUIRED_SCOPE,
            message="The actor cannot read audit legal holds.",
            resource="audit_legal_holds",
        )
        return list_audit_legal_holds(repository, tenant_id)

    @operations_router.post(
        "/audit/legal-holds",
        response_model=AuditLegalHoldRecord,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Audit legal hold permission denied"},
            409: {"description": "Audit legal hold already active"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    def manufacturing_audit_legal_hold_create(
        legal_hold_request: AuditLegalHoldCreateRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> AuditLegalHoldRecord:
        try:
            return create_audit_legal_hold(
                repository,
                _bind_audit_actor(legal_hold_request, principal),
            )
        except AuditLegalHoldPermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot manage audit legal holds.",
                    "required_permissions": [LEGAL_HOLD_REQUIRED_SCOPE],
                    "reason": exc.decision.reason,
                },
            ) from exc
        except AuditLegalHoldConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.POLICY_VIOLATION.value,
                    "message": "The audit legal hold conflicts with existing state.",
                    "hold_id": exc.hold_id,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.post(
        "/audit/legal-holds/{hold_id}/release",
        response_model=AuditLegalHoldRecord,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Audit legal hold permission denied"},
            404: {"description": "Audit legal hold not found"},
            409: {"description": "Audit legal hold is not active"},
        },
        tags=["demo"],
    )
    def manufacturing_audit_legal_hold_release(
        hold_id: str,
        release_request: AuditLegalHoldReleaseRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> AuditLegalHoldRecord:
        if release_request.hold_id != hold_id:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "Path hold_id must match request hold_id.",
                },
            )
        try:
            return release_audit_legal_hold(
                repository,
                _bind_audit_actor(release_request, principal),
            )
        except AuditLegalHoldPermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot manage audit legal holds.",
                    "required_permissions": [LEGAL_HOLD_REQUIRED_SCOPE],
                    "reason": exc.decision.reason,
                },
            ) from exc
        except AuditLegalHoldNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "Audit legal hold record not found.",
                    "hold_id": hold_id,
                },
            ) from exc
        except AuditLegalHoldConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.POLICY_VIOLATION.value,
                    "message": "The audit legal hold conflicts with existing state.",
                    "hold_id": exc.hold_id,
                    "reason": exc.reason,
                },
            ) from exc

    @operations_router.post(
        "/audit/object-legal-holds",
        response_model=AuditObjectLegalHoldRecord,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Audit legal hold permission denied"},
            503: {"description": "Object store cannot enforce object-lock"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["demo"],
    )
    def manufacturing_audit_object_legal_hold_apply(
        hold_request: AuditObjectLegalHoldRequest,
        repository: PersistenceRepository,
        object_store: ConnectorExportObjectStore,
        principal: OidcPrincipalDependency,
    ) -> AuditObjectLegalHoldRecord:
        return _run_object_legal_hold(
            apply_object_legal_hold,
            repository,
            object_store,
            _bind_audit_actor(hold_request, principal),
        )

    @operations_router.post(
        "/audit/object-legal-holds/release",
        response_model=AuditObjectLegalHoldRecord,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Audit legal hold permission denied"},
            503: {"description": "Object store cannot enforce object-lock"},
        },
        tags=["demo"],
    )
    def manufacturing_audit_object_legal_hold_release(
        hold_request: AuditObjectLegalHoldRequest,
        repository: PersistenceRepository,
        object_store: ConnectorExportObjectStore,
        principal: OidcPrincipalDependency,
    ) -> AuditObjectLegalHoldRecord:
        return _run_object_legal_hold(
            release_object_legal_hold,
            repository,
            object_store,
            _bind_audit_actor(hold_request, principal),
        )

    @app.post(
        "/platform/models/endpoints",
        response_model=ModelEndpointRecord,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Model endpoint admin permission denied"},
            409: {"description": "Model endpoint already exists"},
            422: {"description": "Model endpoint validation failed"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["platform"],
    )
    def platform_model_endpoint_create(
        endpoint_request: ModelEndpointCreateRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> ModelEndpointRecord:
        try:
            bound_endpoint = _bind_body_tenant_actor(endpoint_request, principal, "created_by")
            return record_model_endpoint(repository, bound_endpoint)
        except ModelEndpointPermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot administer model endpoints.",
                    "required_permission": exc.required_permission,
                    "reason": "missing_required_scope"
                    if exc.decision.reason.startswith("missing_scope:")
                    else exc.decision.reason,
                    "permission_reason": exc.decision.reason,
                },
            ) from exc
        except ModelEndpointConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.CONFLICT.value,
                    "message": "The model endpoint already exists.",
                    "reason": "endpoint_already_exists",
                    "endpoint_id": exc.endpoint_id,
                },
            ) from exc
        except ModelEndpointValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @app.post(
        "/platform/models/endpoints/{endpoint_id}/status",
        response_model=ModelEndpointRecord,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Model endpoint admin permission denied"},
            404: {"description": "Model endpoint not found"},
            422: {"description": "Model endpoint status transition invalid"},
        },
        tags=["platform"],
    )
    def platform_model_endpoint_status_update(
        endpoint_id: str,
        status_request: ModelEndpointStatusUpdateRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> ModelEndpointRecord:
        try:
            bound_status = _bind_body_tenant_actor(status_request, principal, "updated_by")
            return update_model_endpoint_status(repository, endpoint_id, bound_status)
        except ModelEndpointPermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot administer model endpoints.",
                    "required_permission": exc.required_permission,
                    "reason": "missing_required_scope"
                    if exc.decision.reason.startswith("missing_scope:")
                    else exc.decision.reason,
                    "permission_reason": exc.decision.reason,
                },
            ) from exc
        except ModelEndpointNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "The model endpoint was not found.",
                    "reason": "model_endpoint_not_found",
                    "endpoint_id": exc.endpoint_id,
                },
            ) from exc
        except ModelEndpointValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @app.get(
        "/platform/models/endpoints",
        response_model=ModelEndpointRegistry,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Model endpoint read permission denied"},
        },
        tags=["platform"],
    )
    def platform_model_endpoint_registry(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        status_filter: str | None = Query(default=None, alias="status", min_length=1),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> ModelEndpointRegistry:
        _authorize_model_endpoint_read(
            tenant_id=tenant_id,
            principal=principal,
            resource="model_endpoints",
        )
        return build_model_endpoint_registry(
            repository,
            tenant_id=tenant_id,
            status=status_filter,
            limit=limit,
        )

    @app.post(
        "/platform/models/invocations",
        response_model=ModelInvocationResult,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Model invocation permission denied or egress blocked"},
            409: {"description": "Model invocation idempotency conflict"},
            422: {"description": "Model invocation validation failed"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["platform"],
    )
    async def platform_model_invocation_create(
        invocation_request: ModelInvocationRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        runtime: ModelInvocationRuntimeDependency,
        response: Response,
    ) -> ModelInvocationResult:
        with telemetry.tracer.start_as_current_span("axis.model_invocation.invoke") as span:
            set_span_attributes(
                span,
                {
                    ATTR_TENANT_ID: principal.tenant_id if principal else None,
                    ATTR_ACTOR_ID: principal.actor_id if principal else None,
                },
            )
            try:
                bound_invocation = _bind_body_tenant_actor(
                    invocation_request, principal, "actor_id"
                )
                result = await invoke_model(
                    repository,
                    bound_invocation,
                    runtime,
                    external_model_egress_enabled=(resolved_settings.external_model_egress_enabled),
                    prompt_excerpt_chars=(resolved_settings.model_invocation_prompt_excerpt_chars),
                    usage_metering_enabled=resolved_settings.usage_metering_enabled,
                    usage_window_seconds=(
                        resolved_settings.usage_metering_aggregation_window_seconds
                    ),
                    # This handler owns the request transaction, so the
                    # prepared invocation is committed before the provider
                    # call instead of holding a connection for its duration.
                    commit_before_provider_call=True,
                )
            except ModelInvocationPermissionDenied as exc:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": AxisErrorCode.PERMISSION_DENIED.value,
                        "message": "The actor cannot invoke models.",
                        "required_permission": exc.required_permission,
                        "reason": "missing_required_scope"
                        if exc.decision.reason.startswith("missing_scope:")
                        else exc.decision.reason,
                        "permission_reason": exc.decision.reason,
                    },
                ) from exc
            except PlatformPolicyEnforcementDenied as exc:
                repository.session.commit()
                raise HTTPException(
                    status_code=403,
                    detail=_platform_policy_denied_detail(
                        exc,
                        "A platform policy denies this model invocation.",
                    ),
                ) from exc
            except ModelEgressBlocked as exc:
                repository.session.commit()
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": AxisErrorCode.MODEL_PROVIDER_BLOCKED.value,
                        "message": exc.message,
                        "reason": exc.egress_decision,
                        "endpoint_id": exc.route_decision.endpoint_id,
                        "hosting_boundary": exc.route_decision.hosting_boundary,
                        "audit_event_id": (
                            str(exc.audit_event_id) if exc.audit_event_id is not None else None
                        ),
                        "audit_event_type": exc.audit_event_type,
                    },
                ) from exc
            except ModelInvocationIdempotencyConflict as exc:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": AxisErrorCode.CONFLICT.value,
                        "message": ("The idempotency key already exists with a different payload."),
                        "reason": "idempotency_key_conflict",
                        "invocation_id": str(exc.invocation_id),
                    },
                ) from exc
            except ModelInvocationValidationError as exc:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": AxisErrorCode.VALIDATION_FAILED.value,
                        "message": exc.message,
                        "reason": exc.reason,
                    },
                ) from exc

            set_span_attributes(
                span,
                {
                    ATTR_OUTCOME: result.status,
                    ATTR_MODEL_PROVIDER_ID: result.endpoint_id,
                    ATTR_MODEL_ID: result.model_id,
                    ATTR_MODEL_LATENCY_MS: result.latency_ms,
                    ATTR_MODEL_INPUT_TOKENS: result.input_tokens,
                    ATTR_MODEL_OUTPUT_TOKENS: result.output_tokens,
                },
            )
            if result.idempotent_replay or result.status == "model_invocation_deferred":
                response.status_code = status.HTTP_200_OK
            return result

    @app.post(
        "/platform/models/invocations/preview",
        response_model=ModelInvocationPreview,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Model invocation permission denied"},
        },
        tags=["platform"],
    )
    def platform_model_invocation_preview(
        preview_request: ModelInvocationPreviewRequest,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
    ) -> ModelInvocationPreview:
        try:
            bound_preview = _bind_body_tenant_actor(preview_request, principal, "actor_id")
            return preview_model_invocation(
                repository,
                bound_preview,
                external_model_egress_enabled=(resolved_settings.external_model_egress_enabled),
            )
        except ModelInvocationPermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot preview model invocations.",
                    "required_permission": exc.required_permission,
                    "reason": "missing_required_scope"
                    if exc.decision.reason.startswith("missing_scope:")
                    else exc.decision.reason,
                    "permission_reason": exc.decision.reason,
                },
            ) from exc

    @app.get(
        "/platform/models/invocations",
        response_model=ModelInvocationList,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Model invocation read permission denied"},
            422: {"description": "Model invocation listing cursor is invalid"},
        },
        tags=["platform"],
    )
    def platform_model_invocation_list(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        page_size: int = Query(default=20, ge=1, le=100),
        cursor: str | None = Query(default=None, min_length=1, max_length=600),
    ) -> ModelInvocationList:
        _authorize_model_endpoint_read(
            tenant_id=tenant_id,
            principal=principal,
            resource="model_invocations",
        )
        try:
            cursor_created_at, cursor_row_id = decode_model_invocation_cursor(cursor)
        except ModelInvocationCursorError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "The model invocation listing cursor is invalid.",
                    "reason": exc.reason,
                },
            ) from exc
        results = list_model_invocation_results(
            repository,
            tenant_id,
            cursor_created_at=cursor_created_at,
            cursor_row_id=cursor_row_id,
            limit=page_size + 1,
        )
        has_more = len(results) > page_size
        page_results = results[:page_size]
        next_cursor = (
            encode_model_invocation_cursor(page_results[-1]) if has_more and page_results else None
        )
        return ModelInvocationList(
            tenant_id=tenant_id,
            invocations=page_results,
            has_more=has_more,
            next_cursor=next_cursor,
            invocation_notes=[
                "Invocations are listed newest-first with keyset continuation.",
                "Prompt and response bodies are never persisted; records carry "
                "hashes, token counts and decisions.",
            ],
        )

    @app.get(
        "/platform/models/invocations/{invocation_id}",
        response_model=ModelInvocationResult,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Model invocation read permission denied"},
            404: {"description": "Model invocation not found"},
        },
        tags=["platform"],
    )
    def platform_model_invocation_detail(
        invocation_id: str,
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
    ) -> ModelInvocationResult:
        _authorize_model_endpoint_read(
            tenant_id=tenant_id,
            principal=principal,
            resource="model_invocations",
        )
        try:
            return get_model_invocation_result(repository, tenant_id, invocation_id)
        except ModelInvocationNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "The model invocation was not found.",
                    "reason": "model_invocation_not_found",
                },
            ) from exc

    @app.get(
        "/platform/models/routing/telemetry",
        response_model=ModelRoutingTelemetryProjection,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Model routing telemetry read permission denied"},
        },
        tags=["platform"],
    )
    def platform_model_routing_telemetry(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> ModelRoutingTelemetryProjection:
        _authorize_model_endpoint_read(
            tenant_id=tenant_id,
            principal=principal,
            resource="model_routing_telemetry",
        )
        return build_model_routing_telemetry(
            repository,
            tenant_id,
            limit=limit,
        )

    @operations_router.get(
        "/model-routing",
        response_model=ManufacturingModelRouting,
        responses={
            404: {"description": "Tenant not found"},
            422: {"description": "Model routing reference payload invalid"},
        },
        tags=["demo"],
    )
    def manufacturing_model_routing(
        repository: PersistenceRepository,
        principal: OidcPrincipalDependency,
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
    ) -> ManufacturingModelRouting:
        _authorize_tenant_read(tenant_id, principal)
        try:
            return get_persisted_manufacturing_model_routing(
                repository,
                tenant_id=tenant_id,
            )
        except ModelRoutingReferenceRecordInvalid as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "Manufacturing model routing reference payload is invalid.",
                    "tenant_id": tenant_id,
                    "surface": "model-routing",
                },
            ) from exc

    @operations_router.get(
        "/ontology",
        response_model=ManufacturingOntology,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Ontology graph read permission denied"},
            404: {"description": "Manufacturing ontology reference record not found"},
            422: {"description": "Manufacturing ontology reference payload invalid"},
        },
        tags=["demo"],
    )
    def manufacturing_ontology(
        principal: OidcPrincipalDependency,
        repository: PersistenceRepository,
        ontology_query_runtime: OntologyQueryRuntimeDependency,
        tenant_id: str = Query(min_length=1),
        limit: int = Query(default=200, ge=1, le=500),
    ) -> ManufacturingOntology:
        try:
            authorize_ontology_graph_read(
                repository,
                tenant_id=tenant_id,
                principal=principal,
            )
        except OntologyReadPermissionDenied as exc:
            repository.session.commit()
            raise _ontology_read_denied_http_exception(exc) from exc

        try:
            ontology = get_persisted_manufacturing_ontology(repository, tenant_id=tenant_id)
        except OntologyReferenceRecordNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "Manufacturing ontology reference record not found.",
                    "tenant_id": tenant_id,
                    "surface": "ontology",
                },
            ) from exc
        except OntologyReferenceRecordInvalid as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "Manufacturing ontology reference payload is invalid.",
                    "tenant_id": tenant_id,
                    "surface": "ontology",
                },
            ) from exc

        return query_manufacturing_ontology_graph(
            ontology_query_runtime,
            OntologyGraphQueryRequest(
                tenant_id=tenant_id,
                actor_id=principal.actor_id if principal is not None else "public-demo-reader",
                actor_scopes=principal.scopes if principal is not None else [],
                enforce_relationship_scopes=principal is not None,
                limit=limit,
            ),
            ontology,
        )

    @operations_router.get(
        "/ontology/entities/{node_id:path}",
        response_model=ManufacturingOntologyEntityDetail,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Ontology entity read permission denied"},
            404: {"description": "Manufacturing ontology entity or reference record not found"},
            422: {"description": "Manufacturing ontology reference payload invalid"},
        },
        tags=["demo"],
    )
    def manufacturing_ontology_entity_detail(
        principal: OidcPrincipalDependency,
        repository: PersistenceRepository,
        node_id: str = Path(min_length=1),
        tenant_id: str = Query(min_length=1),
    ) -> ManufacturingOntologyEntityDetail:
        try:
            detail = get_authorized_manufacturing_ontology_entity_detail(
                repository,
                node_id,
                tenant_id=tenant_id,
                principal=principal,
            )
        except OntologyReadPermissionDenied as exc:
            repository.session.commit()
            raise _ontology_read_denied_http_exception(exc) from exc
        except OntologyReferenceRecordNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "Manufacturing ontology reference record not found.",
                    "tenant_id": tenant_id,
                    "surface": "ontology",
                },
            ) from exc
        except OntologyReferenceRecordInvalid as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "Manufacturing ontology reference payload is invalid.",
                    "tenant_id": tenant_id,
                    "surface": "ontology",
                },
            ) from exc
        if detail is None:
            raise HTTPException(status_code=404, detail="Ontology entity not found")
        return detail

    app.include_router(data_router, prefix="/data")
    app.include_router(operations_router, prefix="/operations")
    # Keep the legacy prefix visible as deprecated until clients finish migrating.
    app.include_router(
        operations_router,
        prefix="/demo/manufacturing",
        deprecated=True,
    )
    return app


app = create_app()
