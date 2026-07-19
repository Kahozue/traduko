from . import builtin as _builtin  # noqa: F401  (registers built-in stages)
from . import av as _av  # noqa: F401  (registers audiovisual stages)
from . import audio as _audio  # noqa: F401  (registers audio-domain stages)
from . import agent as _agent  # noqa: F401  (registers agent stages)
from . import doc as _doc  # noqa: F401  (registers document stages)
from . import glossary_proofread as _glossary_proofread  # noqa: F401
from . import dub as _dub  # noqa: F401  (registers dubbing stages)
from . import pdf as _pdf  # noqa: F401  (registers pdf stages)
from . import base, registry

__all__ = ["base", "registry"]
