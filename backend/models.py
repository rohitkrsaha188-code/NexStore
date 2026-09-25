"""Database row representations for nodes, objects, and replicas."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Node:
    node_id: str
    name: str
    status: str = "ONLINE"  # ONLINE/OFFLINE/FAILED/RECOVERING/PARTITIONED/REBALANCING
    health_status: str = "HEALTHY"
    network_status: str = "CONNECTED"
    capacity: int = 10 * 1024**3
    used_capacity: int = 0
    object_count: int = 0
    replica_count: int = 0
    last_heartbeat: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Object:
    object_id: str
    filename: str
    size: int
    checksum: str
    replication_factor: int
    content_type: str = "application/octet-stream"
    version: int = 1
    status: str = "HEALTHY"  # HEALTHY/DEGRADED/REPAIRING/CORRUPTED/UNAVAILABLE/REBALANCING
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Replica:
    replica_id: str
    object_id: str
    node_id: str
    checksum: str
    version: int = 1
    size: int = 0
    status: str = "HEALTHY"  # HEALTHY/MISSING/CORRUPTED/STALE/REPAIRING/UNAVAILABLE
    created_at: str = ""
    updated_at: str = ""
