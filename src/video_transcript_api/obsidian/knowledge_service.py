"""Preview-first, one-way knowledge document synchronization."""

from __future__ import annotations

import difflib
import threading
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

from .knowledge_markdown import (
    managed_document_hash,
    render_analysis_knowledge_markdown,
    render_raw_knowledge_markdown,
)
from .knowledge_models import KnowledgeApplyPrecondition, KnowledgeItem
from .paths import (
    ManagedFileConflict,
    atomic_write_text,
    build_knowledge_directory,
    ensure_vault_directory_tree,
    find_managed_markdown_files,
    resolve_vault_path,
    sanitize_markdown_filename,
)

ABSENT = "__absent__"
_DIFF_LIMIT = 8000


class KnowledgeStalePreview(Exception):
    """Raised when any preview precondition no longer matches."""

    def __init__(self, latest_preview: dict[str, Any] | None = None):
        self.latest_preview = latest_preview
        super().__init__("stale_preview")


class ObsidianKnowledgeService:
    _locks_guard = threading.Lock()
    _locks: dict[str, threading.RLock] = {}

    def __init__(
        self,
        *,
        vault_path: str | Path,
        repository,
        raw_root: str = "raw",
        processed_root: str = "processed",
        now_provider: Callable[[], str] | None = None,
        writer: Callable[[str | Path, str, str], None] | None = None,
    ):
        self.vault_path = Path(vault_path)
        self.repository = repository
        self.raw_root = raw_root
        self.processed_root = processed_root
        self.now_provider = now_provider or (
            lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
        )
        self.writer = writer or atomic_write_text

    @classmethod
    def _lock_for(cls, context_key: str) -> threading.RLock:
        with cls._locks_guard:
            return cls._locks.setdefault(context_key, threading.RLock())

    @staticmethod
    def _identity(item: KnowledgeItem, document_type: str) -> dict[str, str]:
        return {
            "source": "LearnFlux",
            "type": f"learnflux-{document_type}",
            "learnflux_context_key": item.context_key,
        }

    def _candidate_path(
        self,
        directory: str,
        title: str,
        identity: Mapping[str, str],
        *,
        preferred_filename: str | None = None,
    ) -> str:
        directory_path = resolve_vault_path(self.vault_path, directory)
        if directory_path.is_dir():
            matches = find_managed_markdown_files(
                self.vault_path, directory, identity
            )
            if len(matches) > 1:
                raise ManagedFileConflict(
                    "multiple files claim the same managed identity"
                )
            if matches:
                return matches[0]
        filename = preferred_filename or sanitize_markdown_filename(title)
        if (
            PurePosixPath(filename).name != filename
            or not filename.lower().endswith(".md")
        ):
            raise ValueError("preferred filename must be a Markdown basename")
        candidate = PurePosixPath(directory, filename).as_posix()
        path = resolve_vault_path(self.vault_path, candidate)
        stem = path.stem
        suffix = path.suffix
        index = 2
        while path.exists() or path.is_symlink():
            candidate = PurePosixPath(
                directory, f"{stem} ({index}){suffix}"
            ).as_posix()
            path = resolve_vault_path(self.vault_path, candidate)
            index += 1
        return candidate

    def _resolve_path(
        self,
        *,
        item: KnowledgeItem,
        document_type: str,
        directory: str,
        synced_path: str | None,
        preferred_filename: str | None = None,
    ) -> tuple[str, bool]:
        if synced_path:
            old_path = resolve_vault_path(self.vault_path, synced_path)
            if old_path.is_file():
                return synced_path, False
        identity = self._identity(item, document_type)
        directory_path = resolve_vault_path(self.vault_path, directory)
        if directory_path.is_dir():
            matches = find_managed_markdown_files(
                self.vault_path, directory, identity
            )
            if len(matches) > 1:
                raise ManagedFileConflict(
                    "multiple files claim the same managed identity"
                )
            if matches:
                return matches[0], bool(synced_path and matches[0] != synced_path)
        return (
            self._candidate_path(
                directory,
                item.title,
                identity,
                preferred_filename=preferred_filename,
            ),
            False,
        )

    def _documents(
        self,
        item: KnowledgeItem,
        binding: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        collection_directory = str(
            binding.get("collection_directory") or ""
        )
        raw_directory = build_knowledge_directory(
            root=self.raw_root,
            category=str(binding["category"]),
            collection_directory=collection_directory,
        )
        analysis_directory = build_knowledge_directory(
            root=self.processed_root,
            category=str(binding["category"]),
            collection_directory=collection_directory,
        )
        sync = (
            self.repository.get_sync_state(
                item.owner_user_id, item.context_key
            )
            or {}
        )
        raw_path, raw_relocated = self._resolve_path(
            item=item,
            document_type="raw",
            directory=raw_directory,
            synced_path=sync.get("raw_relative_path"),
        )
        analysis_path, analysis_relocated = self._resolve_path(
            item=item,
            document_type="analysis",
            directory=analysis_directory,
            synced_path=sync.get("analysis_relative_path"),
            preferred_filename=PurePosixPath(raw_path).name,
        )
        synced_at = self.now_provider()
        return [
            {
                "document_type": "raw",
                "relative_path": raw_path,
                "content": render_raw_knowledge_markdown(
                    item,
                    category=str(binding["category"]),
                    relative_path=raw_path,
                    synced_at=synced_at,
                ),
                "last_synced_hash": sync.get("raw_synced_hash"),
                "relocated": raw_relocated,
            },
            {
                "document_type": "analysis",
                "relative_path": analysis_path,
                "content": render_analysis_knowledge_markdown(
                    item,
                    category=str(binding["category"]),
                    raw_relative_path=raw_path,
                    relative_path=analysis_path,
                    synced_at=synced_at,
                ),
                "last_synced_hash": sync.get("analysis_synced_hash"),
                "relocated": analysis_relocated,
            },
        ]

    def _preview_document(self, document: Mapping[str, Any]) -> dict[str, Any]:
        path = resolve_vault_path(
            self.vault_path, str(document["relative_path"])
        )
        existing_content = (
            path.read_text(encoding="utf-8") if path.is_file() else ""
        )
        desired_hash = managed_document_hash(str(document["content"]))
        existing_hash = (
            managed_document_hash(existing_content)
            if path.is_file()
            else ABSENT
        )
        last_synced_hash = document.get("last_synced_hash")
        if document.get("relocated"):
            state = "relocated"
        elif existing_hash == ABSENT:
            state = "new"
        elif existing_hash == desired_hash:
            state = "unchanged"
        elif last_synced_hash and existing_hash == last_synced_hash:
            state = "changed"
        else:
            state = "externally_modified"
        if state == "new":
            diff = str(document["content"])[:_DIFF_LIMIT]
        elif state == "unchanged":
            diff = ""
        else:
            diff = "".join(
                difflib.unified_diff(
                    existing_content.splitlines(keepends=True),
                    str(document["content"]).splitlines(keepends=True),
                    fromfile=str(document["relative_path"]),
                    tofile=str(document["relative_path"]),
                )
            )[:_DIFF_LIMIT]
        return {
            "document_type": document["document_type"],
            "relative_path": document["relative_path"],
            "desired_hash": desired_hash,
            "existing_hash": existing_hash,
            "last_synced_hash": last_synced_hash,
            "state": state,
            "diff": diff,
        }

    def preview(
        self,
        *,
        items: Sequence[KnowledgeItem],
        binding: Mapping[str, Any],
        force: bool = False,
    ) -> dict[str, Any]:
        preview_items = []
        preconditions = []
        for item in items:
            documents = [
                self._preview_document(document)
                for document in self._documents(item, binding)
            ]
            for document in documents:
                preconditions.append(
                    {
                        "context_key": item.context_key,
                        "document_type": document["document_type"],
                        "relative_path": document["relative_path"],
                        "desired_hash": document["desired_hash"],
                        "existing_hash": document["existing_hash"],
                    }
                )
            preview_items.append(
                {
                    "context_key": item.context_key,
                    "view_token": item.view_token,
                    "source_id": item.source_id,
                    "source_access": item.source_access,
                    "documents": documents,
                }
            )
        return {
            "binding_revision": binding["revision"],
            "force": bool(force),
            "items": preview_items,
            "preconditions": preconditions,
        }

    @staticmethod
    def _precondition_map(
        conditions: Sequence[
            Mapping[str, Any] | KnowledgeApplyPrecondition
        ],
    ) -> dict[tuple[str, str], tuple[str, str, str]]:
        result = {}
        for condition in conditions:
            if isinstance(condition, KnowledgeApplyPrecondition):
                values = condition.__dict__
            else:
                values = condition
            result[
                (str(values["context_key"]), str(values["document_type"]))
            ] = (
                str(values["relative_path"]),
                str(values["desired_hash"]),
                str(values["existing_hash"]),
            )
        return result

    def apply(
        self,
        *,
        items: Sequence[KnowledgeItem],
        binding: Mapping[str, Any],
        expected_binding_revision: int,
        preconditions: Sequence[
            Mapping[str, Any] | KnowledgeApplyPrecondition
        ],
        force: bool = False,
    ) -> dict[str, Any]:
        if not items:
            return {"items": [], "counts": {}}
        context_keys = sorted({item.context_key for item in items})
        with ExitStack() as stack:
            for context_key in context_keys:
                stack.enter_context(self._lock_for(context_key))
            fresh_binding = self.repository.get_binding(
                items[0].owner_user_id,
                str(binding["scope_type"]),
                str(binding["scope_id"]),
                str(binding["vault_id"]),
            )
            if (
                fresh_binding is None
                or fresh_binding["revision"] != expected_binding_revision
            ):
                raise KnowledgeStalePreview()
            latest = self.preview(
                items=items, binding=fresh_binding, force=force
            )
            actual = self._precondition_map(latest["preconditions"])
            expected = self._precondition_map(preconditions)
            if actual != expected:
                raise KnowledgeStalePreview(latest)

            results = []
            counts = {
                "created": 0,
                "updated": 0,
                "unchanged": 0,
                "failed": 0,
            }
            for item in items:
                item_documents = []
                raw_succeeded = False
                for document in self._documents(item, fresh_binding):
                    document_type = str(document["document_type"])
                    relative_path = str(document["relative_path"])
                    desired_hash = managed_document_hash(
                        str(document["content"])
                    )
                    path = resolve_vault_path(
                        self.vault_path, relative_path
                    )
                    existed = path.is_file()
                    existing_hash = (
                        managed_document_hash(
                            path.read_text(encoding="utf-8")
                        )
                        if existed
                        else ABSENT
                    )
                    if document_type == "analysis" and not raw_succeeded:
                        item_documents.append(
                            {
                                "document_type": document_type,
                                "relative_path": relative_path,
                                "status": "failed",
                                "error_code": "raw_write_failed",
                            }
                        )
                        counts["failed"] += 1
                        continue
                    try:
                        if existing_hash == desired_hash:
                            status = "unchanged"
                        else:
                            ensure_vault_directory_tree(
                                self.vault_path,
                                PurePosixPath(relative_path).parent.as_posix(),
                            )
                            self.writer(
                                self.vault_path,
                                relative_path,
                                str(document["content"]),
                            )
                            status = "updated" if existed else "created"
                        self.repository.update_sync_state(
                            item.owner_user_id,
                            item.context_key,
                            item.view_token,
                            item.collection_id,
                            item.source_id,
                            **{
                                f"{document_type}_relative_path": relative_path,
                                f"{document_type}_synced_hash": desired_hash,
                            },
                        )
                        raw_succeeded = (
                            raw_succeeded or document_type == "raw"
                        )
                        item_documents.append(
                            {
                                "document_type": document_type,
                                "relative_path": relative_path,
                                "status": status,
                            }
                        )
                        counts[status] += 1
                    except Exception as exc:
                        item_documents.append(
                            {
                                "document_type": document_type,
                                "relative_path": relative_path,
                                "status": "failed",
                                "error_code": type(exc).__name__,
                            }
                        )
                        counts["failed"] += 1
                results.append(
                    {
                        "context_key": item.context_key,
                        "view_token": item.view_token,
                        "source_id": item.source_id,
                        "documents": item_documents,
                    }
                )
            return {"items": results, "counts": counts}
