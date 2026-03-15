import sys

from app.ai.providers.opencode import client as _canonical

sys.modules[__name__] = _canonical
