from . import whisper as _whisper  # noqa: F401  (registers builtin providers)
from . import cloud as _cloud  # noqa: F401
from . import macos as _macos  # noqa: F401
from .base import AsrError, AsrProvider, AsrResult, AsrSegment, create_asr, register_asr

__all__ = [
    "AsrError",
    "AsrProvider",
    "AsrResult",
    "AsrSegment",
    "create_asr",
    "register_asr",
]
