"""Evidence-derived lineage for a catalogued data asset.

Lineage chains an asset's ontology proposals to their promotion attempts,
derived from persisted evidence at read time — derivations themselves are
never stored.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from axis_api.data_assets import connector_id_for_asset
from axis_api.models import ConnectorOntologyProposal
from axis_api.persistence import AxisPersistenceRepository


class DataAssetLineagePromotion(BaseModel):
    promotion_id: str
    status: str
    promotion_mode: str
    requested_by: str
    created_at: datetime


class DataAssetLineageProposal(BaseModel):
    proposal_id: str
    status: str
    graph_mutation_status: str
    node_id: str
    ontology_type: str
    proposed_by: str
    created_at: datetime
    promoted_at: datetime | None = None
    promotions: list[DataAssetLineagePromotion] = Field(default_factory=list)


class DataAssetLineageView(BaseModel):
    tenant_id: str
    asset_id: str
    proposals: list[DataAssetLineageProposal] = Field(default_factory=list)


def build_data_asset_lineage_view(
    repository: AxisPersistenceRepository,
    *,
    tenant_id: str,
    asset_id: str,
) -> DataAssetLineageView:
    """Derive the proposal/promotion chain for one catalogued asset."""
    connector_id = connector_id_for_asset(repository, tenant_id=tenant_id, asset_id=asset_id)
    proposals = sorted(
        repository.list_connector_ontology_proposals(
            tenant_id,
            connector_id=connector_id,
            limit=200,
        ),
        key=lambda proposal: (proposal.created_at, proposal.proposal_id),
    )
    return DataAssetLineageView(
        tenant_id=tenant_id,
        asset_id=asset_id,
        proposals=[
            _lineage_proposal_view(repository, tenant_id, proposal)
            for proposal in proposals
        ],
    )


def _lineage_proposal_view(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    proposal: ConnectorOntologyProposal,
) -> DataAssetLineageProposal:
    promotions = sorted(
        repository.list_connector_ontology_promotions(
            tenant_id,
            proposal_id=proposal.proposal_id,
            limit=50,
        ),
        key=lambda promotion: (promotion.created_at, promotion.promotion_id),
    )
    return DataAssetLineageProposal(
        proposal_id=proposal.proposal_id,
        status=proposal.status,
        graph_mutation_status=proposal.graph_mutation_status,
        node_id=proposal.node_id,
        ontology_type=proposal.ontology_type,
        proposed_by=proposal.proposed_by,
        created_at=proposal.created_at,
        promoted_at=proposal.promoted_at,
        promotions=[
            DataAssetLineagePromotion(
                promotion_id=promotion.promotion_id,
                status=promotion.status,
                promotion_mode=promotion.promotion_mode,
                requested_by=promotion.requested_by,
                created_at=promotion.created_at,
            )
            for promotion in promotions
        ],
    )
