"""DEADLOOP Python SDK — lightweight, dependency-free event instrumentation."""

from .client import DeadloopClient, DeadloopError, Event

__all__ = ["DeadloopClient", "DeadloopError", "Event"]
__version__ = "0.1.0"
