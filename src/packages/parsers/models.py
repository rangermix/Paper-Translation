"""Read-only parser contract identity. Importing never prepares model weights."""
from .profiles import DEFAULT_PROFILE, selected_profile


def parser_version(profile=DEFAULT_PROFILE):
    selected_profile({'parser_profile_revision': profile})
    from .catalog import vlm_lock
    return vlm_lock()['adapter_version']
