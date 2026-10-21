from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import threading
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable

PROFILE_DOCUMENT_CATEGORIES = (
    "master_profile",
    "skills",
    "projects",
    "experience",
    "certifications",
    "education",
    "achievements",
)


def profile_documents_revision(documents: dict[str, Any]) -> str:
    encoded = json.dumps(
        documents,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

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


class DocumentHistoryError(RuntimeError):
    """Raised when document history cannot be read or persisted safely."""


class DocumentHistoryMigrationError(DocumentHistoryError):
    """Raised when legacy history cannot be imported without ambiguity."""


class DocumentHistoryConflictError(DocumentHistoryError):
    """Raised when a document-history identifier conflicts with stored data."""


def _normalize_document_history(history: Any, *, require_application_id: bool = False) -> dict[str, Any]:
    if not isinstance(history, dict) or not isinstance(history.get("documents"), list):
        raise DocumentHistoryError("Document history must be an object containing a documents list.")

    normalized = copy.deepcopy(history)
    seen_ids: set[str] = set()
    for entry in normalized["documents"]:
        if not isinstance(entry, dict):
            raise DocumentHistoryError("Every document-history entry must be an object.")
        document_id = entry.get("document_id")
        if document_id is None:
            document_id = uuid.uuid4().hex
            entry["document_id"] = document_id
        if not isinstance(document_id, str) or not document_id:
            raise DocumentHistoryError("Every document-history entry must have a non-empty document_id.")
        if document_id in seen_ids:
            raise DocumentHistoryConflictError(f"Duplicate document-history ID: {document_id}")
        seen_ids.add(document_id)
        if require_application_id and (
            not isinstance(entry.get("application_id"), str) or not entry["application_id"]
        ):
            raise DocumentHistoryMigrationError(
                f"Document-history entry {document_id} has no valid application_id."
            )
        try:
            json.dumps(entry, ensure_ascii=False, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise DocumentHistoryError(f"Document-history entry {document_id} is not valid JSON: {exc}") from exc
    return normalized


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

    @abstractmethod
    def load_document_history(self) -> dict[str, Any]:
        """Load document-history entries without changing their payload shape."""

    @abstractmethod
    def save_document_history(self, history: dict[str, Any]) -> None:
        """Replace the full document-history snapshot atomically."""

    @abstractmethod
    def append_document_history(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Append one document-history entry and return it with its stable ID."""

    @abstractmethod
    def replace_document_history_entry(
        self, document_id: str, entry: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Replace one entry while preserving its stable ID."""

    @abstractmethod
    def delete_document_history_entry(self, document_id: str) -> dict[str, Any] | None:
        """Delete one entry by its stable ID."""

    @abstractmethod
    def insert_application(self, application: dict[str, Any]) -> None:
        """Insert one new application without replacing other records."""

    @abstractmethod
    def mutate_application(
        self,
        application_id: str,
        mutation: Callable[[dict[str, Any]], bool | None],
    ) -> dict[str, Any] | None:
        """Apply a mutation to the current version of one application."""

    @abstractmethod
    def delete_application(
        self,
        application_id: str,
        expected: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Delete one application, optionally only if it still matches a snapshot."""


class FileStorageAdapter(StorageAdapter):
    """File-backed adapter for local development or an explicitly selected file mode."""

    backend_name = "file"
    _application_lock = threading.RLock()

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
        with self._application_lock:
            path = self.data_dir / "applications.json"
            loaded = self._read_json_file(path, EMPTY_APPLICATION_STORE)
            return self.translate_application_store(loaded)

    def save_application_store(self, store: dict[str, Any]) -> None:
        with self._application_lock:
            payload = self.translate_application_store(store)
            path = self.data_dir / "applications.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _read_document_history(self) -> dict[str, Any]:
        path = self.data_dir / "document_history.json"
        if not path.exists():
            return {"documents": []}
        try:
            raw_history = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise DocumentHistoryError(f"Document history could not be read safely: {exc}") from exc
        history = _normalize_document_history(raw_history)
        if history != raw_history:
            self._write_document_history(history)
        return history

    def _write_document_history(self, history: dict[str, Any]) -> None:
        payload = _normalize_document_history(history)
        path = self.data_dir / "document_history.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(str(temporary), str(path))
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def load_document_history(self) -> dict[str, Any]:
        with self._application_lock:
            return self._read_document_history()

    def save_document_history(self, history: dict[str, Any]) -> None:
        with self._application_lock:
            self._read_document_history()
            self._write_document_history(history)

    def append_document_history(self, entry: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(entry, dict):
            raise DocumentHistoryError("A document-history entry must be an object.")
        with self._application_lock:
            history = self._read_document_history()
            candidate = copy.deepcopy(entry)
            candidate.setdefault("document_id", uuid.uuid4().hex)
            normalized = _normalize_document_history({"documents": [*history["documents"], candidate]})
            self._write_document_history(normalized)
            return copy.deepcopy(normalized["documents"][-1])

    def replace_document_history_entry(
        self, document_id: str, entry: dict[str, Any]
    ) -> dict[str, Any] | None:
        if not isinstance(entry, dict):
            raise DocumentHistoryError("A document-history entry must be an object.")
        if entry.get("document_id") not in (None, document_id):
            raise DocumentHistoryConflictError(
                "A document-history replacement cannot change its document_id."
            )
        with self._application_lock:
            history = self._read_document_history()
            for index, current in enumerate(history["documents"]):
                if current.get("document_id") == document_id:
                    replacement = copy.deepcopy(entry)
                    replacement["document_id"] = document_id
                    history["documents"][index] = replacement
                    self._write_document_history(history)
                    return copy.deepcopy(replacement)
            return None

    def delete_document_history_entry(self, document_id: str) -> dict[str, Any] | None:
        with self._application_lock:
            history = self._read_document_history()
            for index, current in enumerate(history["documents"]):
                if current.get("document_id") == document_id:
                    deleted = history["documents"].pop(index)
                    self._write_document_history(history)
                    return copy.deepcopy(deleted)
            return None

    def insert_application(self, application: dict[str, Any]) -> None:
        application_id = application.get("application_id")
        if not application_id:
            raise ValueError("Application ID is required.")
        with self._application_lock:
            store = self.load_application_store()
            if any(item.get("application_id") == application_id for item in store["applications"]):
                raise ValueError(f"Application already exists: {application_id}")
            store["applications"].append(copy.deepcopy(application))
            self.save_application_store(store)

    def mutate_application(
        self,
        application_id: str,
        mutation: Callable[[dict[str, Any]], bool | None],
    ) -> dict[str, Any] | None:
        with self._application_lock:
            store = self.load_application_store()
            application = next(
                (item for item in store["applications"] if item.get("application_id") == application_id),
                None,
            )
            if application is None:
                return None
            if mutation(application) is False:
                return None
            self.save_application_store(store)
            return copy.deepcopy(application)

    def delete_application(
        self,
        application_id: str,
        expected: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        with self._application_lock:
            store = self.load_application_store()
            application = next(
                (item for item in store["applications"] if item.get("application_id") == application_id),
                None,
            )
            if application is None or (expected is not None and application != expected):
                return None
            store["applications"] = [
                item for item in store["applications"] if item.get("application_id") != application_id
            ]
            self.save_application_store(store)
            return copy.deepcopy(application)
