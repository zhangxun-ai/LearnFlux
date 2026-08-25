"""Lazy public exports for transcription components.

Keeping package import side effects minimal allows the persistence layer to use
the database adapter during early configuration loading without importing ASR
clients and the logging stack recursively.
"""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    "Transcriber": (".transcriber", "Transcriber"),
    "FunASRSpeakerClient": (".funasr_client", "FunASRSpeakerClient"),
    "CapsWriterClient": (".capswriter_client", "CapsWriterClient"),
    "TranscriptionContext": (".contracts", "TranscriptionContext"),
    "TranscriptionProvider": (".contracts", "TranscriptionProvider"),
    "TranscriptionResult": (".contracts", "TranscriptionResult"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
