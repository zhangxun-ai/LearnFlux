"""Obsidian note reconciliation and local synchronization orchestration."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from ..study.repository import StudyRepository, build_study_context_key
from .markdown import (
    extract_note_body,
    managed_identity,
    managed_markdown_hash,
    note_body_hash,
    render_note_markdown,
    render_transcript_markdown,
)
from .paths import (
    ManagedFileConflict,
    VaultPathError,
    allocate_managed_markdown_path,
    atomic_write_text,
    find_managed_markdown_files,
    resolve_vault_path,
)


ABSENT_FILE_HASH = "__absent__"


@dataclass(frozen=True)
class NoteReconciliation:
    state: str
    app_hash: str
    obsidian_hash: str
    baseline_hash: Optional[str]


@dataclass(frozen=True)
class StudySyncContext:
    owner_user_id: str
    view_token: str
    title: str
    course: str
    transcript_lines: list[dict[str, Any]]
    collection_id: str = ""
    source_id: str = ""


class ObsidianConflict(Exception):
    """Raised when synchronization requires an explicit user decision."""

    def __init__(self, payload: dict[str, Any]):
        super().__init__(payload.get("code") or payload.get("state") or "obsidian conflict")
        self.payload = payload


class ObsidianSyncError(Exception):
    """Raised for stable, user-actionable synchronization failures."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def reconcile_note_state(
    *,
    app_body: str,
    obsidian_exists: bool,
    obsidian_body: Optional[str],
    baseline_hash: Optional[str],
) -> NoteReconciliation:
    """Classify the three-way app/Obsidian/baseline note state."""
    app_hash = note_body_hash(app_body)
    obsidian_hash = (
        note_body_hash(obsidian_body or "") if obsidian_exists else ABSENT_FILE_HASH
    )

    if baseline_hash is not None and not obsidian_exists:
        state = "external_deleted"
    elif baseline_hash is None:
        if not obsidian_exists:
            state = "app_dirty" if app_body else "skipped_empty"
        elif app_hash == obsidian_hash:
            state = "converged"
        elif not app_body:
            state = "obsidian_dirty"
        elif not (obsidian_body or ""):
            state = "app_dirty"
        else:
            state = "conflict"
    elif app_hash == baseline_hash and obsidian_hash == baseline_hash:
        state = "clean"
    elif app_hash != baseline_hash and obsidian_hash == baseline_hash:
        state = "app_dirty"
    elif app_hash == baseline_hash and obsidian_hash != baseline_hash:
        state = "obsidian_dirty"
    elif app_hash == obsidian_hash:
        state = "converged"
    else:
        state = "conflict"

    return NoteReconciliation(
        state=state,
        app_hash=app_hash,
        obsidian_hash=obsidian_hash,
        baseline_hash=baseline_hash,
    )


class ObsidianSyncService:
    """Synchronize one managed transcript and note per Study context."""

    def __init__(
        self,
        *,
        vault_id: str,
        vault_path: str | Path,
        repository: StudyRepository,
        now_provider: Callable[[], str],
    ):
        self.vault_id = vault_id
        self.vault_path = Path(vault_path).expanduser()
        self.repository = repository
        self.now_provider = now_provider
        self._locks_guard = threading.Lock()
        self._locks: dict[str, threading.RLock] = {}

    def _lock_for(self, context: StudySyncContext) -> threading.RLock:
        key = (
            f"{context.owner_user_id}|"
            f"{build_study_context_key(context.view_token, context.collection_id, context.source_id)}"
        )
        with self._locks_guard:
            return self._locks.setdefault(key, threading.RLock())

    @staticmethod
    def _scope(context: StudySyncContext) -> tuple[str, str]:
        if context.collection_id:
            return "collection", context.collection_id
        return "single", context.view_token

    def get_binding(self, context: StudySyncContext) -> Optional[dict[str, Any]]:
        scope_type, scope_id = self._scope(context)
        return self.repository.get_obsidian_binding(
            owner_user_id=context.owner_user_id,
            scope_type=scope_type,
            scope_id=scope_id,
            vault_id=self.vault_id,
        )

    def save_binding(
        self,
        context: StudySyncContext,
        *,
        transcript_directory: str,
        note_directory: str,
        expected_revision: Optional[int],
    ) -> dict[str, Any]:
        transcript_path = resolve_vault_path(self.vault_path, transcript_directory)
        note_path = resolve_vault_path(self.vault_path, note_directory)
        if not transcript_path.is_dir() or not note_path.is_dir():
            raise ObsidianSyncError("binding_directory_missing")
        scope_type, scope_id = self._scope(context)
        return self.repository.save_obsidian_binding(
            owner_user_id=context.owner_user_id,
            scope_type=scope_type,
            scope_id=scope_id,
            vault_id=self.vault_id,
            transcript_directory=transcript_directory,
            note_directory=note_directory,
            expected_revision=expected_revision,
        )

    def markdown_metadata(self, context: StudySyncContext) -> dict[str, str]:
        return {
            "view_token": context.view_token,
            "collection_id": context.collection_id,
            "source_id": context.source_id,
            "course": context.course,
            "lesson": context.title,
            "synced_at": self.now_provider(),
        }

    def _get_document(self, context: StudySyncContext) -> dict[str, Any]:
        return self.repository.get_or_create_note_document(
            owner_user_id=context.owner_user_id,
            view_token=context.view_token,
            collection_id=context.collection_id,
            source_id=context.source_id,
            claim_unowned_single_legacy=not bool(context.collection_id),
        )

    def save_note(
        self,
        context: StudySyncContext,
        *,
        body: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        return self.repository.update_note_document(
            owner_user_id=context.owner_user_id,
            view_token=context.view_token,
            collection_id=context.collection_id,
            source_id=context.source_id,
            body=body,
            expected_revision=expected_revision,
        )

    def _get_sync_state(self, context: StudySyncContext) -> dict[str, Any]:
        return self.repository.update_obsidian_source_sync(
            owner_user_id=context.owner_user_id,
            view_token=context.view_token,
            collection_id=context.collection_id,
            source_id=context.source_id,
        )

    def _find_note_file(
        self,
        context: StudySyncContext,
        binding: dict[str, Any],
    ) -> tuple[Optional[str], Optional[str]]:
        identity = managed_identity(
            "study-note",
            view_token=context.view_token,
            collection_id=context.collection_id,
            source_id=context.source_id,
        )
        matches = find_managed_markdown_files(
            self.vault_path, binding["note_directory"], identity
        )
        if len(matches) > 1:
            raise ObsidianConflict(
                {"code": "managed_identity_conflict", "state": "conflict"}
            )
        if not matches:
            return None, None
        relative_path = matches[0]
        path = resolve_vault_path(self.vault_path, relative_path)
        return relative_path, path.read_text(encoding="utf-8")

    @staticmethod
    def _conflict_payload(
        document: dict[str, Any],
        reconciliation: NoteReconciliation,
        obsidian_body: Optional[str],
        *,
        code: Optional[str] = None,
    ) -> dict[str, Any]:
        return {
            "code": code or reconciliation.state,
            "state": reconciliation.state,
            "app_body": document["body"],
            "obsidian_body": obsidian_body,
            "preconditions": {
                "expected_revision": document["revision"],
                "expected_obsidian_hash": reconciliation.obsidian_hash,
                "expected_baseline_hash": reconciliation.baseline_hash,
            },
        }

    def load_note(self, context: StudySyncContext) -> dict[str, Any]:
        """Load and reconcile Obsidian-only changes without overwriting files."""
        with self._lock_for(context):
            document = self._get_document(context)
            binding = self.get_binding(context)
            if binding is None:
                return {"document": document, "state": "binding_required"}
            self._validate_binding(binding)
            sync_state = self._get_sync_state(context)
            note_path, note_content = self._find_note_file(context, binding)
            note_exists = note_content is not None
            obsidian_body = extract_note_body(note_content) if note_exists else None
            reconciliation = reconcile_note_state(
                app_body=document["body"],
                obsidian_exists=note_exists,
                obsidian_body=obsidian_body,
                baseline_hash=sync_state.get("note_body_synced_hash"),
            )

            if reconciliation.state == "obsidian_dirty":
                document = self.repository.update_note_document(
                    owner_user_id=context.owner_user_id,
                    view_token=context.view_token,
                    collection_id=context.collection_id,
                    source_id=context.source_id,
                    body=obsidian_body or "",
                    expected_revision=document["revision"],
                )
                self.repository.update_obsidian_source_sync(
                    owner_user_id=context.owner_user_id,
                    view_token=context.view_token,
                    collection_id=context.collection_id,
                    source_id=context.source_id,
                    note_relative_path=note_path,
                    note_body_synced_hash=note_body_hash(obsidian_body or ""),
                    note_managed_hash=managed_markdown_hash(note_content or ""),
                    synced_at=self.now_provider(),
                )
                return {
                    "document": document,
                    "state": "clean",
                    "reconciled_from": "obsidian",
                }

            if reconciliation.state == "converged":
                self.repository.update_obsidian_source_sync(
                    owner_user_id=context.owner_user_id,
                    view_token=context.view_token,
                    collection_id=context.collection_id,
                    source_id=context.source_id,
                    note_relative_path=note_path,
                    note_body_synced_hash=reconciliation.app_hash,
                    note_managed_hash=managed_markdown_hash(note_content or ""),
                    synced_at=self.now_provider(),
                )
                return {"document": document, "state": "clean"}

            result = {"document": document, "state": reconciliation.state}
            if reconciliation.state in {"conflict", "external_deleted"}:
                result["conflict"] = self._conflict_payload(
                    document, reconciliation, obsidian_body
                )
            return result

    def _validate_binding(self, binding: dict[str, Any]) -> None:
        for key in ("transcript_directory", "note_directory"):
            try:
                directory = resolve_vault_path(self.vault_path, binding[key])
            except (OSError, VaultPathError) as exc:
                raise ObsidianSyncError("binding_directory_missing") from exc
            if not directory.is_dir():
                raise ObsidianSyncError("binding_directory_missing")

    def inspect_conflict(self, context: StudySyncContext) -> dict[str, Any]:
        loaded = self.load_note(context)
        conflict = loaded.get("conflict")
        if conflict is None:
            raise ObsidianSyncError("conflict_not_found")
        return conflict

    def _allocate_transcript_path(
        self,
        context: StudySyncContext,
        binding: dict[str, Any],
    ) -> str:
        identity = managed_identity(
            "transcript",
            view_token=context.view_token,
            collection_id=context.collection_id,
            source_id=context.source_id,
        )
        return allocate_managed_markdown_path(
            self.vault_path, binding["transcript_directory"], context.title, identity
        )

    def _allocate_note_path(
        self,
        context: StudySyncContext,
        binding: dict[str, Any],
    ) -> str:
        identity = managed_identity(
            "study-note",
            view_token=context.view_token,
            collection_id=context.collection_id,
            source_id=context.source_id,
        )
        return allocate_managed_markdown_path(
            self.vault_path, binding["note_directory"], context.title, identity
        )

    def sync(self, context: StudySyncContext) -> dict[str, Any]:
        """Synchronize both files, returning truthful per-file status."""
        with self._lock_for(context):
            if not any(
                str(line.get("text") or "").strip()
                for line in context.transcript_lines
            ):
                raise ObsidianSyncError("transcript_not_ready")
            loaded = self.load_note(context)
            if loaded["state"] == "binding_required":
                return {"overall": "binding_required"}
            if loaded["state"] in {"conflict", "external_deleted"}:
                raise ObsidianConflict(loaded["conflict"])
            binding = self.get_binding(context)
            if binding is None:
                return {"overall": "binding_required"}
            self._validate_binding(binding)
            document = loaded["document"]
            sync_state = self._get_sync_state(context)
            metadata = self.markdown_metadata(context)

            transcript_path = self._allocate_transcript_path(context, binding)
            transcript_target = resolve_vault_path(self.vault_path, transcript_path)
            transcript_existed = transcript_target.is_file()
            transcript_content = render_transcript_markdown(
                metadata, context.transcript_lines
            )
            transcript_hash = managed_markdown_hash(transcript_content)
            transcript_unchanged = (
                transcript_existed
                and managed_markdown_hash(
                    transcript_target.read_text(encoding="utf-8")
                )
                == transcript_hash
            )

            note_path, existing_note_content = self._find_note_file(context, binding)
            if note_path is None and document["body"]:
                note_path = self._allocate_note_path(context, binding)
            note_content = None
            note_hash = None
            note_existed = False
            note_unchanged = False
            if note_path is not None:
                note_target = resolve_vault_path(self.vault_path, note_path)
                note_existed = note_target.is_file()
                note_content = render_note_markdown(
                    metadata,
                    document["body"],
                    existing_content=existing_note_content,
                )
                note_hash = managed_markdown_hash(note_content)
                note_unchanged = (
                    note_existed
                    and existing_note_content is not None
                    and managed_markdown_hash(existing_note_content) == note_hash
                )

            transcript_result = self._write_transcript(
                context,
                transcript_path,
                transcript_content,
                transcript_hash,
                existed=transcript_existed,
                unchanged=transcript_unchanged,
            )
            note_result = self._write_note(
                context,
                document,
                note_path,
                note_content,
                note_hash,
                existed=note_existed,
                unchanged=note_unchanged,
            )

            failed = sum(
                result["status"] == "failed"
                for result in (transcript_result, note_result)
            )
            if failed == 0:
                overall = "success"
            elif failed == 2:
                overall = "failed"
            else:
                overall = "partial"
            return {
                "overall": overall,
                "transcript": transcript_result,
                "note": note_result,
            }

    def _write_transcript(
        self,
        context: StudySyncContext,
        relative_path: str,
        content: str,
        content_hash: str,
        *,
        existed: bool,
        unchanged: bool,
    ) -> dict[str, Any]:
        try:
            if not unchanged:
                atomic_write_text(self.vault_path, relative_path, content)
            self.repository.update_obsidian_source_sync(
                owner_user_id=context.owner_user_id,
                view_token=context.view_token,
                collection_id=context.collection_id,
                source_id=context.source_id,
                transcript_relative_path=relative_path,
                transcript_synced_hash=content_hash,
                synced_at=self.now_provider(),
            )
            status = "unchanged" if unchanged else ("updated" if existed else "created")
            return {"status": status, "relative_path": relative_path}
        except (OSError, UnicodeError, VaultPathError):
            return {"status": "failed", "error_code": "transcript_write_failed"}

    def _write_note(
        self,
        context: StudySyncContext,
        document: dict[str, Any],
        relative_path: Optional[str],
        content: Optional[str],
        content_hash: Optional[str],
        *,
        existed: bool,
        unchanged: bool,
    ) -> dict[str, Any]:
        if relative_path is None or content is None or content_hash is None:
            return {"status": "skipped_empty", "relative_path": None}
        try:
            if not unchanged:
                atomic_write_text(self.vault_path, relative_path, content)
            self.repository.update_obsidian_source_sync(
                owner_user_id=context.owner_user_id,
                view_token=context.view_token,
                collection_id=context.collection_id,
                source_id=context.source_id,
                note_relative_path=relative_path,
                note_body_synced_hash=note_body_hash(document["body"]),
                note_managed_hash=content_hash,
                synced_at=self.now_provider(),
            )
            status = "unchanged" if unchanged else ("updated" if existed else "created")
            return {"status": status, "relative_path": relative_path}
        except (OSError, UnicodeError, VaultPathError):
            return {"status": "failed", "error_code": "note_write_failed"}

    def resolve_conflict(
        self,
        context: StudySyncContext,
        *,
        choice: str,
        expected_revision: int,
        expected_obsidian_hash: str,
        expected_baseline_hash: Optional[str],
    ) -> dict[str, Any]:
        """Resolve a conflict only if the preview preconditions still hold."""
        with self._lock_for(context):
            loaded = self.load_note(context)
            conflict = loaded.get("conflict")
            if conflict is None:
                raise ObsidianConflict(
                    {
                        "code": "stale_conflict",
                        "state": loaded["state"],
                        "preconditions": {},
                    }
                )
            actual = conflict["preconditions"]
            expected = {
                "expected_revision": expected_revision,
                "expected_obsidian_hash": expected_obsidian_hash,
                "expected_baseline_hash": expected_baseline_hash,
            }
            if actual != expected:
                stale = dict(conflict)
                stale["code"] = "stale_conflict"
                raise ObsidianConflict(stale)

            document = loaded["document"]
            binding = self.get_binding(context)
            if binding is None:
                raise ObsidianSyncError("binding_required")
            note_path, note_content = self._find_note_file(context, binding)
            obsidian_body = extract_note_body(note_content) if note_content is not None else None

            if choice == "accept_external_deletion" and conflict["state"] == "external_deleted":
                document = self.repository.update_note_document(
                    owner_user_id=context.owner_user_id,
                    view_token=context.view_token,
                    collection_id=context.collection_id,
                    source_id=context.source_id,
                    body="",
                    expected_revision=document["revision"],
                )
                self.repository.update_obsidian_source_sync(
                    owner_user_id=context.owner_user_id,
                    view_token=context.view_token,
                    collection_id=context.collection_id,
                    source_id=context.source_id,
                    note_relative_path=None,
                    note_body_synced_hash=None,
                    note_managed_hash=None,
                    synced_at=None,
                )
                return {"document": document, "note_relative_path": None}

            if choice == "obsidian" and note_content is not None:
                document = self.repository.update_note_document(
                    owner_user_id=context.owner_user_id,
                    view_token=context.view_token,
                    collection_id=context.collection_id,
                    source_id=context.source_id,
                    body=obsidian_body or "",
                    expected_revision=document["revision"],
                )
                self.repository.update_obsidian_source_sync(
                    owner_user_id=context.owner_user_id,
                    view_token=context.view_token,
                    collection_id=context.collection_id,
                    source_id=context.source_id,
                    note_relative_path=note_path,
                    note_body_synced_hash=note_body_hash(obsidian_body or ""),
                    note_managed_hash=managed_markdown_hash(note_content),
                    synced_at=self.now_provider(),
                )
                return {"document": document, "note_relative_path": note_path}

            valid_app_choice = choice == "app" and conflict["state"] == "conflict"
            valid_recreate = (
                choice == "recreate_from_app"
                and conflict["state"] == "external_deleted"
            )
            if not (valid_app_choice or valid_recreate):
                raise ObsidianSyncError("invalid_conflict_choice")
            if note_path is None:
                note_path = self._allocate_note_path(context, binding)
            rendered = render_note_markdown(
                self.markdown_metadata(context),
                document["body"],
                existing_content=note_content,
            )
            atomic_write_text(self.vault_path, note_path, rendered)
            self.repository.update_obsidian_source_sync(
                owner_user_id=context.owner_user_id,
                view_token=context.view_token,
                collection_id=context.collection_id,
                source_id=context.source_id,
                note_relative_path=note_path,
                note_body_synced_hash=note_body_hash(document["body"]),
                note_managed_hash=managed_markdown_hash(rendered),
                synced_at=self.now_provider(),
            )
            return {"document": document, "note_relative_path": note_path}
