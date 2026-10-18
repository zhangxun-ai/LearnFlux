"""Preview-first, one-way knowledge document synchronization."""

from __future__ import annotations

import difflib
import re
import threading
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

from .knowledge_markdown import (
    COLLECTION_INDEX_TITLE,
    content_hash,
    parse_knowledge_markdown,
    is_collection_index_item,
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

    @staticmethod
    def _type_identity(document_type: str) -> dict[str, str]:
        return {
            "source": "LearnFlux",
            "type": f"learnflux-{document_type}",
        }

    @staticmethod
    def _view_token_identity(item: KnowledgeItem, document_type: str) -> dict[str, str]:
        return {
            "source": "LearnFlux",
            "type": f"learnflux-{document_type}",
            "learnflux_view_token": item.view_token,
        }

    def _unique_managed_match(
        self,
        directory: str,
        identity: Mapping[str, str],
    ) -> str | None:
        directory_path = resolve_vault_path(self.vault_path, directory)
        if not directory_path.is_dir():
            return None
        matches = find_managed_markdown_files(
            self.vault_path, directory, identity
        )
        if len(matches) > 1:
            raise ManagedFileConflict(
                "multiple files claim the same managed identity"
            )
        return matches[0] if matches else None

    def _managed_filename_path(
        self,
        directory: str,
        filename: str,
        document_type: str,
    ) -> str | None:
        """Reuse an existing LearnFlux-managed note with the preferred basename.

        When users re-import a course under a new collection_id but the same
        Vault folder, context_key changes. Prefer overwriting the canonical
        filename instead of allocating ``name (2).md`` duplicates.
        """
        if (
            PurePosixPath(filename).name != filename
            or not filename.lower().endswith(".md")
        ):
            raise ValueError("preferred filename must be a Markdown basename")
        candidate = PurePosixPath(directory, filename).as_posix()
        path = resolve_vault_path(self.vault_path, candidate)
        if not path.is_file():
            return None
        # Only reclaim LearnFlux-managed notes of the same document layer.
        managed = find_managed_markdown_files(
            self.vault_path,
            directory,
            self._type_identity(document_type),
        )
        return candidate if candidate in managed else None

    def _candidate_path(
        self,
        directory: str,
        title: str,
        identity: Mapping[str, str],
        *,
        preferred_filename: str | None = None,
        item: KnowledgeItem | None = None,
        document_type: str = "raw",
        reclaim_by_filename: bool = True,
        reserved_paths: set[str] | None = None,
    ) -> str:
        reserved_paths = reserved_paths if reserved_paths is not None else set()
        exact = self._unique_managed_match(directory, identity)
        if exact and exact not in reserved_paths:
            return exact

        filename = preferred_filename or sanitize_markdown_filename(title)
        if (
            PurePosixPath(filename).name != filename
            or not filename.lower().endswith(".md")
        ):
            raise ValueError("preferred filename must be a Markdown basename")

        # 1) Canonical filename already managed by LearnFlux → overwrite.
        reclaimed = (self._managed_filename_path(
            directory, filename, document_type
        ) if reclaim_by_filename else None)
        if reclaimed and reclaimed not in reserved_paths:
            return reclaimed

        # 2) Same view_token (stable content identity across re-collections).
        if item and item.view_token:
            by_token = self._unique_managed_match(
                directory, self._view_token_identity(item, document_type)
            )
            if by_token and by_token not in reserved_paths:
                return by_token

        candidate = PurePosixPath(directory, filename).as_posix()
        path = resolve_vault_path(self.vault_path, candidate)
        stem = path.stem
        suffix = path.suffix
        index = 2
        while path.exists() or path.is_symlink() or candidate in reserved_paths:
            # Prefer reclaiming LearnFlux-managed collision names with same token.
            collision = PurePosixPath(
                directory, f"{stem} ({index}){suffix}"
            ).as_posix()
            candidate = collision
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
        reclaim_by_filename: bool = True,
        reserved_paths: set[str] | None = None,
    ) -> tuple[str, bool, bool]:
        """Return ``(relative_path, relocated, reclaimed_managed)``.

        ``reclaimed_managed`` is True when an existing LearnFlux note was reused
        under a new context_key (e.g. re-imported collection) so preview can
        treat identity/frontmatter updates as normal ``changed`` writes.
        """
        reserved_paths = reserved_paths if reserved_paths is not None else set()
        if synced_path and synced_path not in reserved_paths:
            old_path = resolve_vault_path(self.vault_path, synced_path)
            if old_path.is_file() and PurePosixPath(synced_path).parent == PurePosixPath(directory):
                return synced_path, False, False
        identity = self._identity(item, document_type)
        exact = self._unique_managed_match(directory, identity)
        if exact and exact not in reserved_paths:
            return exact, bool(synced_path and exact != synced_path), False

        filename = preferred_filename or sanitize_markdown_filename(item.title)
        reclaimed = (self._managed_filename_path(
            directory, filename, document_type
        ) if reclaim_by_filename else None)
        if reclaimed and reclaimed not in reserved_paths:
            return (
                reclaimed,
                bool(synced_path and reclaimed != synced_path),
                True,
            )

        if item.view_token:
            by_token = self._unique_managed_match(
                directory, self._view_token_identity(item, document_type)
            )
            if by_token and by_token not in reserved_paths:
                return (
                    by_token,
                    bool(synced_path and by_token != synced_path),
                    True,
                )

        return (
            self._candidate_path(
                directory,
                item.title,
                identity,
                preferred_filename=preferred_filename,
                item=item,
                document_type=document_type,
                reclaim_by_filename=reclaim_by_filename,
                reserved_paths=reserved_paths,
            ),
            False,
            False,
        )

    @staticmethod
    def _document_types(document_types: Sequence[str]) -> tuple[str, ...]:
        if not document_types or any(value not in {"raw", "analysis"} for value in document_types):
            raise ValueError("invalid_document_types")
        return tuple(value for value in ("raw", "analysis") if value in document_types)

    def _documents(
        self,
        item: KnowledgeItem,
        binding: Mapping[str, Any],
        *,
        target_directory: str | None = None,
        document_types: Sequence[str] = ("raw", "analysis"),
        reserved_paths: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        selected = self._document_types(document_types)
        if target_directory is not None:
            resolve_vault_path(self.vault_path, target_directory, allow_empty=True)
            directories = {
                "raw": PurePosixPath(target_directory, "逐字稿").as_posix(),
                "analysis": PurePosixPath(target_directory, "AI 总结").as_posix(),
            }
        else:
            directories = {
                kind: build_knowledge_directory(
                    root=root,
                    category=str(binding["category"]),
                    collection_directory=str(binding.get("collection_directory") or ""),
                )
                for kind, root in (("raw", self.raw_root), ("analysis", self.processed_root))
            }
        sync = self.repository.get_sync_state(item.owner_user_id, item.context_key) or {}
        preferred_name = f"{COLLECTION_INDEX_TITLE}.md" if is_collection_index_item(item) else None
        raw_path = ""
        documents = []
        synced_at = self.now_provider()
        for kind in selected:
            relative_path, relocated, reclaimed = self._resolve_path(
                item=item,
                document_type=kind,
                directory=directories[kind],
                synced_path=sync.get(f"{kind}_relative_path"),
                preferred_filename=PurePosixPath(raw_path).name if raw_path else preferred_name,
                reclaim_by_filename=target_directory is None,
                reserved_paths=reserved_paths,
            )
            if reserved_paths is not None:
                reserved_paths.add(relative_path)
            if kind == "raw":
                raw_path = relative_path
                content = render_raw_knowledge_markdown(
                    item, category=str(binding["category"]),
                    relative_path=relative_path, synced_at=synced_at,
                )
            else:
                content = render_analysis_knowledge_markdown(
                    item, category=str(binding["category"]),
                    raw_relative_path=raw_path,
                    relative_path=relative_path, synced_at=synced_at,
                )
            documents.append({
                "document_type": kind,
                "relative_path": relative_path,
                "content": content,
                "last_synced_hash": sync.get(f"{kind}_synced_hash"),
                "relocated": relocated,
                "reclaimed_managed": reclaimed,
            })
        return documents

    def _plan_documents(
        self,
        items: Sequence[KnowledgeItem],
        binding: Mapping[str, Any],
        *,
        target_directory: str | None,
        document_types: Sequence[str],
    ) -> list[tuple[KnowledgeItem, list[dict[str, Any]]]]:
        """Allocate the complete batch before writing, including duplicate titles."""
        reserved_paths: set[str] = set()
        planned = [
            (item, self._documents(
                item, binding, target_directory=target_directory,
                document_types=document_types, reserved_paths=reserved_paths,
            ))
            for item in items
        ]
        if target_directory is not None:
            for index_item, documents in planned:
                if not is_collection_index_item(index_item):
                    continue
                for chapter, chapter_documents in planned:
                    if is_collection_index_item(chapter) or chapter.collection_id != index_item.collection_id:
                        continue
                    stem = sanitize_markdown_filename(chapter.title).removesuffix(".md")
                    prefix = f"- {chapter.position:02d}. [[{stem}]]"
                    paths = {doc["document_type"]: doc["relative_path"] for doc in chapter_documents}
                    for document in documents:
                        note_path = paths[document["document_type"]].removesuffix(".md")
                        replacement = f"- {chapter.position:02d}. [[{note_path}|{stem}]]"
                        document["content"] = re.sub(
                            "^" + re.escape(prefix), lambda _match: replacement,
                            document["content"], flags=re.MULTILINE,
                        )
                for document in documents:
                    # Link allocation changes the body after rendering; keep its
                    # stored hash consistent without altering other frontmatter.
                    _fields, body = parse_knowledge_markdown(document["content"])
                    header, separator, rest = document["content"].partition("\n---\n")
                    header = re.sub(
                        r"^content_hash:.*$", f"content_hash: {content_hash(body)}",
                        header, flags=re.MULTILINE,
                    )
                    document["content"] = header + separator + rest
        return planned

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
        if (
            existing_hash != ABSENT
            and last_synced_hash
            and existing_hash not in {last_synced_hash, desired_hash}
        ):
            state = "externally_modified"
        elif document.get("relocated"):
            state = "relocated"
        elif existing_hash == ABSENT:
            state = "new"
        elif existing_hash == desired_hash:
            state = "unchanged"
        elif last_synced_hash and existing_hash == last_synced_hash:
            state = "changed"
        elif document.get("reclaimed_managed"):
            # Same-folder re-import with a new collection/source identity should
            # overwrite the previous LearnFlux note rather than look external.
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
        target_directory: str | None = None,
        document_types: Sequence[str] = ("raw", "analysis"),
    ) -> dict[str, Any]:
        document_types = self._document_types(document_types)
        if target_directory is not None:
            resolve_vault_path(self.vault_path, target_directory, allow_empty=True)
        planned = self._plan_documents(
            items, binding, target_directory=target_directory, document_types=document_types
        )
        preview_items = []
        preconditions = []
        for item, item_documents in planned:
            documents = [self._preview_document(document) for document in item_documents]
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
            "target_directory": target_directory,
            "document_types": list(document_types),
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
        target_directory: str | None = None,
        document_types: Sequence[str] = ("raw", "analysis"),
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
                items=items, binding=fresh_binding, force=force,
                target_directory=target_directory, document_types=document_types
            )
            actual = self._precondition_map(latest["preconditions"])
            expected = self._precondition_map(preconditions)
            if actual != expected:
                raise KnowledgeStalePreview(latest)

            if not force and any(
                document["state"] == "externally_modified"
                for preview_item in latest["items"]
                for document in preview_item["documents"]
            ):
                raise ManagedFileConflict("externally modified notes require explicit overwrite")

            planned = self._plan_documents(
                items, fresh_binding, target_directory=target_directory, document_types=document_types
            )
            results = []
            counts = {
                "created": 0,
                "updated": 0,
                "unchanged": 0,
                "failed": 0,
            }
            for item, documents in planned:
                item_documents = []
                raw_succeeded = "raw" not in document_types
                for document in documents:
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
            return {"items": results, "counts": counts,
                    "target_directory": target_directory, "document_types": list(document_types)}
