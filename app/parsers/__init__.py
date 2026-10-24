"""Versioned, composable workflow adapters. Readers never interpret workflow nodes."""

from .pipeline import parse_metadata

__all__ = ["parse_metadata"]
