"""NB contracts: content diagnostics describe results, never grant execution."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CONTENT_POLICY = 'nonblocking-v1'
COMPLETED_STATES = frozenset({'succeeded', 'completed', 'completed_with_warnings', 'partially_completed'})
TERMINAL_STATES = COMPLETED_STATES | {'failed', 'cancelled'}
WAITING_STATES = frozenset({'paused', 'waiting_config', 'waiting_configuration', 'waiting_budget', 'outcome_unknown'})


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class QualitySummary(Contract):
    state: Literal['not_checked', 'checking', 'completed', 'stale', 'failed'] = 'not_checked'
    important: int = Field(default=0, ge=0)
    general: int = Field(default=0, ge=0)
    info: int = Field(default=0, ge=0)
    diagnostic_count: int = Field(default=0, ge=0)
    blocking: Literal[False] = False


class ContentIssue(Contract):
    id: str
    stage: str
    category: str
    severity: Literal['important', 'general', 'info']
    page: int | None = Field(default=None, ge=1)
    block_ids: list[str] = Field(default_factory=list)
    bbox: tuple[float, float, float, float] | None = None
    message: str
    evidence_refs: list[str] = Field(default_factory=list)
    diagnostic_count: int = Field(default=1, ge=1)
    recovery: dict | None = None
    status: Literal['open', 'recovered', 'retained', 'acknowledged'] = 'open'
    blocking: Literal[False] = False


class ModelIdentity(Contract):
    kind: Literal['none', 'local', 'api', 'historical_unknown']
    model_id: str | None = None
    models: list[dict] = Field(default_factory=list)
    parser_profile_revision: str | None = None
    revision: str | None = None
    engine: str | None = None
    engine_version: str | None = None
    device: str | None = None
    backend: str | None = None
    layout_device: str | None = None
    inference_engine: str | None = None
    model_artifact_id: str | None = None
    threads: int | None = None
    timeout_seconds: int | None = None
    provider: str | None = None
    api_protocol: str | None = None
    endpoint: str | None = None
    config_revision: str | None = None
    evidence_source: str | None = None
