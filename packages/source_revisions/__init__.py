"""Evidence-bound PDF source correction and conservative revision mapping."""
from .corrections import apply_corrections, revision_mapping
from .native import apply_native_corrections, native_regions_for_block

__all__ = ['apply_corrections', 'revision_mapping', 'apply_native_corrections', 'native_regions_for_block']
