from __future__ import annotations

import copy
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

PROFILE_DOCUMENT_CATEGORIES = (
    "master_profile",
    "skills",
    "projects",
    "experience",
    "certifications",
    "education",
    "achievements",
)

EMPTY_PROFILE_DOCUMENTS: dict[str, dict[str, Any]] = {
    "master_profile": {
        "profile": {},
        "source_documents": [],
        "record_indexes": {},
        "conflicts_requiring_review": [],
    },
    "skills": {"skill_groups": []},
    "projects": {"projects": []},
    "experience": {"experiences": []},
    "certifications": {"certifications": []},
    "education": {"education": []},
    "achievements": {"achievements": []},
}

EMPTY_APPLICATION_STORE: dict[str, list[dict[str, Any]]] = {"applications": []}


def _deep_merge(base: Any, incoming: Any) -> Any:
    if isinstance(base, dict) and isinstance(incoming, dict):
        merged = copy.deepcopy(base)
        for key, value in incoming.items():
            if key in merged:
                merged[key] = _deep_merge(merged[key], value)
            else:
                merged[key] = copy.deepcopy(value)
        return merged
    return copy.deepcopy(incoming)


class StorageAdapter(ABC):
    """Compatibility-first storage interface for the current application payloads."""

    backend_name = "storage"

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root).expanduser().resolve() if root is not None else Path(__file__).resolve().parent

    @staticmethod
    def translate_profile_document(category: str, payload: Any) -> dict[str, Any]:
        default = EMPTY_PROFILE_DOCUMENTS.get(category, {})
        if payload is None:
            return copy.deepcopy(default)
        if not isinstance(payload, dict):
            return copy.deepcopy(default)
        return _deep_merge(default, payload)

    @classmethod
    def normalize_profile_documents(cls, documents: dict[str, Any] | None) -> dict[str, Any]:
        normalized = {category: cls.translate_profile_document(category, documents.get(category) if documents else None) for category in PROFILE_DOCUMENT_CATEGORIES}
        if documents:
            for category, value in documents.items():
                if category in PROFILE_DOCUMENT_CATEGORIES:
                    normalized[category] = cls.translate_profile_document(category, value)
                else:
                    normalized[category] = copy.deepcopy(value)
        return normalized

    @staticmethod
    def translate_application_store(store: dict[str, Any] | None) -> dict[str, Any]:
        normalized = copy.deepcopy(EMPTY_APPLICATION_STORE)
        if isinstance(store, dict):
            applications = store.get("applications")
            if isinstance(applications, list):
                normalized["applications"] = copy.deepcopy(applications)
        return normalized

    @staticmethod
    def translate_application_record(record: Any) -> dict[str, Any]:
        if isinstance(record, dict):
            return copy.deepcopy(record)
        return {}

    @abstractmethod
    def is_ready(self) -> bool:
        """Return whether the adapter is configured for a backend without yet making it live."""

    @abstractmethod
    def validate(self) -> list[str]:
        """Return any configuration or translation issues."""

    @abstractmethod
    def load_profile_documents(self) -> dict[str, Any]:
        """Load all canonical profile document payloads without changing caller shapes."""

    @abstractmethod
    def save_profile_documents(self, documents: dict[str, Any]) -> None:
        """Persist the app-facing profile document dictionary without mutating semantics."""

    @abstractmethod
    def load_application_store(self) -> dict[str, Any]:
        """Load the app-facing application store payload."""

    @abstractmethod
    def save_application_store(self, store: dict[str, Any]) -> None:
        """Persist the app-facing application store payload."""


class FileStorageAdapter(StorageAdapter):
    """Compatibility adapter that keeps the existing file-backed implementation as the fallback path."""

    backend_name = "file"

    def __init__(self, root: str | Path | None = None):
        super().__init__(root=root)
        self.data_dir = Path(self.root) / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def is_ready(self) -> bool:
        return self.data_dir.exists()

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.data_dir.exists():
            try:
                self.data_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:  # pragma: no cover - OS-level failure case
                errors.append(f"Unable to create storage data directory: {exc}")
        return errors

    def _read_json_file(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return copy.deepcopy(default)
        try:
            text = path.read_text(encoding="utf-8")
            if not text.strip():
                return copy.deepcopy(default)
            loaded = json.loads(text)
        except (json.JSONDecodeError, OSError):
            return copy.deepcopy(default)
        return loaded

    def load_profile_documents(self) -> dict[str, Any]:
        documents: dict[str, Any] = {}
        for category in PROFILE_DOCUMENT_CATEGORIES:
            path = self.data_dir / f"{category}.json"
            documents[category] = self._read_json_file(path, EMPTY_PROFILE_DOCUMENTS[category])
        return self.normalize_profile_documents(documents)

    def save_profile_documents(self, documents: dict[str, Any]) -> None:
        payload = self.normalize_profile_documents(documents)
        for category in PROFILE_DOCUMENT_CATEGORIES:
            path = self.data_dir / f"{category}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload[category], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def load_application_store(self) -> dict[str, Any]:
        path = self.data_dir / "applications.json"
        loaded = self._read_json_file(path, EMPTY_APPLICATION_STORE)
        return self.translate_application_store(loaded)

    def save_application_store(self, store: dict[str, Any]) -> None:
        payload = self.translate_application_store(store)
        path = self.data_dir / "applications.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
