"""Installed source and resource roots, independent of the working directory."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / 'src'
RESOURCE_ROOT = ROOT / 'res'
