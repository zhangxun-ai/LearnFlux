"""PostgreSQL storage for parsed transcript and LLM artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable

from ..transcriber.control_database import PostgresControlDatabase


@dataclass(frozen=True)
class Artifact:
    artifact_type: str
    original_name: str
    content: bytes
    content_sha256: str
    byte_size: int

    def text(self) -> str:
        return self.content.decode("utf-8")

    def json(self) -> Any:
        return json.loads(self.text())


class PostgresArtifactStore:
    """Read and write exact UTF-8 artifact bytes keyed by ``video_cache.id``."""

    def __init__(self, database: PostgresControlDatabase) -> None:
        self.database = database

    @staticmethod
    def build(
        artifact_type: str, original_name: str, content: bytes | str
    ) -> Artifact:
        raw = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        return Artifact(
            artifact_type=artifact_type,
            original_name=original_name,
            content=raw,
            content_sha256=hashlib.sha256(raw).hexdigest(),
            byte_size=len(raw),
        )

    @staticmethod
    def put_with_connection(connection, cache_id: int, artifact: Artifact) -> None:
        connection.execute(
            """
            INSERT INTO transcription_artifacts(
                cache_id, artifact_type, original_name, content,
                content_sha256, byte_size, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(cache_id, artifact_type) DO UPDATE SET
                original_name = excluded.original_name,
                content = excluded.content,
                content_sha256 = excluded.content_sha256,
                byte_size = excluded.byte_size,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                cache_id,
                artifact.artifact_type,
                artifact.original_name,
                artifact.content,
                artifact.content_sha256,
                artifact.byte_size,
            ),
        )

    def put(self, cache_id: int, artifact: Artifact) -> None:
        with self.database.transaction() as connection:
            self.put_with_connection(connection, cache_id, artifact)

    def put_many(self, cache_id: int, artifacts: Iterable[Artifact]) -> None:
        with self.database.transaction() as connection:
            for artifact in artifacts:
                self.put_with_connection(connection, cache_id, artifact)

    def get_all(self, cache_id: int, *, connection=None) -> dict[str, Artifact]:
        owns_connection = connection is None
        connection = connection or self.database.connect()
        try:
            rows = connection.execute(
                """
                SELECT artifact_type, original_name, content,
                       content_sha256, byte_size
                FROM transcription_artifacts
                WHERE cache_id = ?
                """,
                (cache_id,),
            ).fetchall()
            return {
                str(row["artifact_type"]): Artifact(
                    artifact_type=str(row["artifact_type"]),
                    original_name=str(row["original_name"]),
                    content=bytes(row["content"]),
                    content_sha256=str(row["content_sha256"]),
                    byte_size=int(row["byte_size"]),
                )
                for row in rows
            }
        finally:
            if owns_connection:
                connection.close()

    def find_cache_id(
        self,
        platform: str,
        media_id: str,
        use_speaker_recognition: bool | None = None,
    ) -> int | None:
        clauses = ["platform = ?", "media_id = ?"]
        params: list[Any] = [platform, media_id]
        if use_speaker_recognition is not None:
            clauses.append("use_speaker_recognition = ?")
            params.append(int(use_speaker_recognition))
        connection = self.database.connect()
        try:
            row = connection.execute(
                f"""
                SELECT id FROM video_cache
                WHERE {' AND '.join(clauses)}
                ORDER BY use_speaker_recognition DESC, updated_at DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
            return int(row["id"]) if row else None
        finally:
            connection.close()
