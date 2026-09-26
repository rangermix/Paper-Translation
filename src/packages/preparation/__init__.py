"""Source-grounded, versioned translation preparation; no implicit network access."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class PreparationOptions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Literal['off', 'extractive', 'provider', 'local'] = 'extractive'


def freeze_options(options, translation_profile):
    """Freeze only a specifically chosen backend; reading this never downloads."""
    from packages.domain.errors import require
    options = PreparationOptions.model_validate(options or {}).model_dump()
    if options['mode'] == 'provider':
        require(translation_profile.get('api_protocol') != 'local_translation', 'PREPARATION_ANALYST_REQUIRED')
    if options['mode'] == 'local':
        from packages.providers.local_analysis import profile
        return {'preparation_options': options, 'analysis_profile': profile()}
    return {'preparation_options': options}
