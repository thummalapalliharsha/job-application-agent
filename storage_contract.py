"""Abstract storage contract for the durable-storage adapter phase.

This module defines the minimum interface expected by the application before any
actual PostgreSQL persistence is connected. The implementation remains intentionally
non-persistent and does not execute SQL.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class StorageAdapter(ABC):
    """Storage adapter contract for future durable persistence.

    The adapter is intentionally compatibility-focused: it is designed to preserve the
    current JSON payload shapes used by the application while allowing a PostgreSQL
    backend to be introduced later without altering the existing caller contracts.
    """

    backend_name: str = "file"

    @abstractmethod
    def is_ready(self) -> bool:
        """Return whether the adapter is configured and ready for future persistence."""

    @abstractmethod
    def validate(self) -> list[str]:
        """Return validation errors for the current storage configuration."""

    @abstractmethod
    def storage_reference(self, path: str | Path, root: str | Path | None = None) -> str:
        """Return the compatibility storage reference string for a file path."""

    @abstractmethod
    def resolve_storage_reference(
        self, reference: str, root: str | Path | None = None
    ) -> Path | None:
        """Resolve a compatibility storage reference back to a filesystem path."""

    @abstractmethod
    def load_profile_documents(self) -> dict[str, Any]:
        """Return the canonical dictionary keyed by profile category."""

    @abstractmethod
    def save_profile_documents(self, documents: dict[str, Any]) -> None:
        """Persist the canonical document bundle without changing app-facing shapes."""

    @abstractmethod
    def load_application_store(self) -> dict[str, Any]:
        """Return the application store payload expected by the current app."""

    @abstractmethod
    def save_application_store(self, store: dict[str, Any]) -> None:
        """Persist the application store payload without changing schemas."""
