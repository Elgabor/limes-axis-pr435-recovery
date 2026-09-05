from pydantic import BaseModel, Field


class WorkflowStartRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    workflow_type: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    payload: dict


class WorkflowState(BaseModel):
    workflow_id: str
    status: str
    payload: dict
