"""Pydantic schemas used by the REST API layer."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class NodeOut(BaseModel):
    node_id: str
    name: str
    status: str
    health_status: str
    network_status: str
    capacity: int
    used_capacity: int
    object_count: int
    replica_count: int
    utilization: float = 0.0
    last_heartbeat: str
    created_at: str
    updated_at: str


class ReplicaOut(BaseModel):
    replica_id: str
    object_id: str
    node_id: str
    node_name: str = ""
    checksum: str
    version: int
    size: int
    status: str
    created_at: str
    updated_at: str


class ObjectOut(BaseModel):
    object_id: str
    filename: str
    size: int
    content_type: str
    checksum: str
    version: int
    replication_factor: int
    status: str
    replica_count: int = 0
    healthy_replicas: int = 0
    required_replicas: int = 0
    missing_replicas: int = 0
    created_at: str
    updated_at: str


class UploadResponse(BaseModel):
    object_id: str
    filename: str
    size: int
    checksum: str
    version: int
    replication_factor: int
    status: str
    replicas: list[ReplicaOut]
    placement: dict[str, Any]


class FileDetail(ObjectOut):
    replicas: list[ReplicaOut]


class DownloadResponse(BaseModel):
    object_id: str
    filename: str
    size: int
    checksum: str
    version: int
    served_from_node: str
    served_from_replica: str
    integrity: str


class VerifyResponse(BaseModel):
    object_id: str
    replicas_checked: int
    verified: int
    corrupted: int
    repaired_scheduled: int
    integrity: str
    results: list[dict[str, Any]]


class CorruptResponse(BaseModel):
    replica_id: str
    node_id: str
    object_id: str
    detected: bool


class NodeActionResponse(BaseModel):
    node_id: str
    status: str
    network_status: str
    message: str


class RepairJobOut(BaseModel):
    repair_id: str
    object_id: str
    filename: str = ""
    replica_id: str
    failed_node_id: Optional[str]
    replacement_node_id: Optional[str]
    reason: str
    status: str
    progress: int
    started_at: Optional[str]
    completed_at: Optional[str]
    duration_ms: Optional[int]
    error: Optional[str]


class RebalanceJobOut(BaseModel):
    job_id: str
    object_id: str
    filename: str = ""
    replica_id: str
    source_node_id: str
    dest_node_id: str
    status: str
    progress: int
    bytes_moved: int
    started_at: Optional[str]
    completed_at: Optional[str]


class ActivityOut(BaseModel):
    id: int
    event_type: str
    message: str
    object_id: Optional[str]
    node_id: Optional[str]
    created_at: str


class SystemStats(BaseModel):
    status: str
    app_name: str
    total_capacity: int
    used_capacity: int
    available_capacity: int
    logical_storage: int
    physical_storage: int
    replication_overhead: int
    replication_factor: int
    total_objects: int
    total_replicas: int
    nodes_total: int
    nodes_online: int
    nodes_failed: int
    nodes_partitioned: int
    active_repair_jobs: int
    completed_repairs: int
    failed_repairs: int
    avg_repair_ms: Optional[int]
    corrupted_replicas: int
    system_health: str


class HealthResponse(BaseModel):
    status: str
    nodes: int
    healthy_nodes: int
    failed_nodes: int


class SettingsOut(BaseModel):
    replication_factor: int
    health_check_interval: int
    repair_interval: int
    integrity_check_interval: int
    rebalance_threshold: int
    max_storage_per_node: int


class SettingsUpdate(BaseModel):
    replication_factor: Optional[int] = Field(default=None, ge=1, le=5)
    health_check_interval: Optional[int] = Field(default=None, ge=1, le=3600)
    repair_interval: Optional[int] = Field(default=None, ge=1, le=3600)
    integrity_check_interval: Optional[int] = Field(default=None, ge=1, le=86400)
    rebalance_threshold: Optional[int] = Field(default=None, ge=10, le=99)
    max_storage_per_node: Optional[int] = Field(default=None, ge=1024 * 1024)


class VersionConflictDetail(BaseModel):
    current_version: int
    provided_version: int
