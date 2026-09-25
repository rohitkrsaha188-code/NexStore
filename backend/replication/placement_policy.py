"""Placement policy shared by replication subsystem (delegates to storage)."""
from backend.storage.placement import PlacementPolicy

__all__ = ["PlacementPolicy"]
