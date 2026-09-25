"""Domain exceptions mapped to HTTP responses by the API layer."""
from __future__ import annotations


class VaultError(Exception):
    """Base class for all Vault errors."""

    status_code = 500
    error = "internal_error"

    def __init__(self, message: str = "", detail: dict | None = None) -> None:
        super().__init__(message or self.__class__.__name__)
        self.message = message or self.__class__.__name__
        self.detail = detail or {}


class NotFoundError(VaultError):
    status_code = 404
    error = "not_found"


class ObjectNotFoundError(NotFoundError):
    error = "object_not_found"


class NodeNotFoundError(NotFoundError):
    error = "node_not_found"


class ReplicaNotFoundError(NotFoundError):
    error = "replica_not_found"


class ConflictError(VaultError):
    status_code = 409
    error = "conflict"


class VersionConflictError(ConflictError):
    error = "version_conflict"


class InsufficientNodesError(ConflictError):
    error = "insufficient_healthy_nodes"


class StorageFullError(ConflictError):
    error = "storage_full"


class ObjectUnavailableError(ConflictError):
    error = "object_unavailable"


class ValidationError(VaultError):
    status_code = 422
    error = "validation_error"


class PayloadTooLargeError(VaultError):
    status_code = 413
    error = "payload_too_large"


class InvalidFilenameError(ValidationError):
    error = "invalid_filename"
