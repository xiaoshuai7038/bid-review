import sys

from app.ai.providers.claude import client as _canonical

sys.modules[__name__] = _canonical
