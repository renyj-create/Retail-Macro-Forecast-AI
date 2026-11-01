from typing import Literal
from pydantic import BaseModel, Field, ConfigDict

class RawField(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(max_length=80)
    raw_text: str | None = Field(default=None, max_length=300)
    unit: str | None = Field(default=None, max_length=30)

class Extraction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    document_type: Literal['operating_report', 'unknown']
    fields: list[RawField] = Field(max_length=100)

class Issue(BaseModel):
    field: str
    code: str
    message: str

class ValidatedField(RawField):
    normalized_value: str | None = None
    normalized_unit: str | None = None
    validation_status: Literal['valid', 'invalid', 'missing']

class Evidence(BaseModel):
    evidence_id: str
    source_type: Literal['image_extraction'] = 'image_extraction'
    data_nature: Literal['user_uploaded_unverified', 'simulated']
    source_sha256: str
    verification: str = 'unverified'

class AnalysisResponse(BaseModel):
    task_id: str
    status: Literal['success','needs_review','mock','failed','not_configured']
    error_code: str | None = None
    message: str = ''
    document_type: str | None = None
    provider: str
    is_mock: bool = False
    fields: list[ValidatedField] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    evidence: Evidence
    report: str = ''
    report_status: Literal['template', 'unavailable'] = 'unavailable'
