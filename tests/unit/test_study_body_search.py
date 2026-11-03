"""Artifact cache invalidation and bounded reads for PostgreSQL-shaped storage."""

from types import SimpleNamespace
import sqlite3

from video_transcript_api.study.body_search import authorized_body_texts, matching_excerpt


def test_postgres_artifacts_are_scoped_cached_and_invalidated_by_digest():
    # The SQL contract is shared through the production qmark adapter. A local
    # database exercises the real query and byte decoding without a server.
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE transcription_artifacts (cache_id INTEGER, artifact_type TEXT, content BLOB, content_sha256 TEXT)")
    conn.executemany("INSERT INTO transcription_artifacts VALUES (?,?,?,?)", [
        (1, "llm_calibrated", b"Visible first result", "first-hash"),
        (2, "llm_calibrated", b"Private second result", "second-hash"),
    ])
    manager = SimpleNamespace(_is_postgres=True, database=object())
    statements = []
    conn.set_trace_callback(statements.append)
    first = authorized_body_texts(conn, "", manager, [1])
    assert set(first) == {"1"}
    assert matching_excerpt(first["1"], "first") == "Visible first result"
    assert all("Private" not in text for texts in first.values() for text in texts)
    statements.clear()
    second = authorized_body_texts(conn, "", manager, [1])
    assert second == first
    assert not any("artifact_type, content," in sql for sql in statements)
    conn.execute("UPDATE transcription_artifacts SET content=?,content_sha256=? WHERE cache_id=1", (b"Visible updated result", "updated-hash"))
    updated = authorized_body_texts(conn, "", manager, [1])
    assert matching_excerpt(updated["1"], "first") is None
    assert matching_excerpt(updated["1"], "updated") is not None
    conn.close()


def test_same_digest_and_id_in_separate_databases_does_not_share_private_content():
    def database(content):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE transcription_artifacts (cache_id INTEGER, artifact_type TEXT, content BLOB, content_sha256 TEXT)")
        conn.execute("INSERT INTO transcription_artifacts VALUES (1,'llm_summary',?,'same-digest')", (content,))
        return conn

    first, second = database(b"First installation"), database(b"Second installation")
    assert authorized_body_texts(first, "", SimpleNamespace(_is_postgres=True, database=object()), [1])["1"] == ["First installation"]
    assert authorized_body_texts(second, "", SimpleNamespace(_is_postgres=True, database=object()), [1])["1"] == ["Second installation"]
    first.close()
    second.close()
