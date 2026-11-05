"""Collector package: source adapters and time-ordered incident grouping."""
from collector.adapters import (
    BandAdapter,
    CollectorPipeline,
    GitAdapter,
    TerminalAdapter,
)

__all__ = ["BandAdapter", "CollectorPipeline", "GitAdapter", "TerminalAdapter"]

