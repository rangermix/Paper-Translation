from pydantic import BaseModel, ConfigDict, Field


class ResourcePolicy(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    max_ram_percent: int = Field(80, ge=1, le=100)
    max_vram_percent: int = Field(80, ge=1, le=100)
    master_concurrency: int = Field(2, ge=1, le=8)
    subjob_concurrency: int = Field(1, ge=1, le=8)
    auto_concurrency: bool = True


def policy(preferences=None):
    return ResourcePolicy.model_validate((preferences or {}).get('resources', {})).model_dump()


WORKER_LIMIT = 16
