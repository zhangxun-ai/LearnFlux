import importlib

_TRANSCRIPTION_EXPORTS = {
    "TranscribeRequest",
    "TranscribeResponse",
    "process_llm_queue",
    "process_task_queue",
    "verify_token",
}

__all__ = sorted(_TRANSCRIPTION_EXPORTS)


def __getattr__(name: str):
    if name in _TRANSCRIPTION_EXPORTS:
        transcription = importlib.import_module(".transcription", __name__)
        value = getattr(transcription, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
