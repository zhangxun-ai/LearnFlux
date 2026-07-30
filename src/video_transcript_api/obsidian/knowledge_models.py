"""Domain models for one-way LearnFlux knowledge deposits."""

from __future__ import annotations

from dataclasses import dataclass

from ..study.repository import build_study_context_key


@dataclass(frozen=True)
class KnowledgeItem:
    owner_user_id: str
    view_token: str
    title: str
    raw_content: str
    analysis_content: str
    source_kind: str
    source_access: str
    collection_id: str = ""
    source_id: str = ""
    collection_title: str = ""
    collection_creator: str = ""
    position: int = 0

    @property
    def context_key(self) -> str:
        return build_study_context_key(self.view_token, self.collection_id, self.source_id)


@dataclass(frozen=True)
class KnowledgeDocumentPreview:
    document_type: str
    relative_path: str
    desired_hash: str
    existing_hash: str
    last_synced_hash: str | None
    state: str
    diff: str = ""


@dataclass(frozen=True)
class KnowledgeItemPreview:
    context_key: str
    view_token: str
    documents: tuple[KnowledgeDocumentPreview, ...]
    source_access: str = ""


@dataclass(frozen=True)
class KnowledgeApplyPrecondition:
    context_key: str
    document_type: str
    relative_path: str
    desired_hash: str
    existing_hash: str
