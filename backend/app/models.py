from typing import Literal, Optional
from pydantic import BaseModel, Field


ModeType = Literal["council", "conversation"]


class ModelCatalogItem(BaseModel):
    id: str
    provider: str = "litellm"
    underlying_model: Optional[str] = None
    input_cost_per_token: Optional[float] = None
    output_cost_per_token: Optional[float] = None
    max_tokens: Optional[int] = None


class AttachmentPayload(BaseModel):
    filename: str
    mime_type: str = "text/plain"
    extracted_text: str
    char_count: int


class CreateRunRequest(BaseModel):
    session_id: Optional[str] = None
    mode: ModeType
    prompt: str = Field(..., min_length=1)
    models: list[str] = Field(..., min_length=2, max_length=5)
    chairman_model: Optional[str] = "auto"
    shared_constraints: Optional[str] = None
    attachments: list[AttachmentPayload] = Field(default_factory=list)


class PresetCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    mode: ModeType
    models: list[str] = Field(..., min_length=2, max_length=5)
    chairman_model: Optional[str] = "auto"
    shared_constraints: Optional[str] = None


class RenameSessionRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=160)
