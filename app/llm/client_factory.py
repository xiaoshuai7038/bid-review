import sys

from app.ai.providers import factory as _canonical

sys.modules[__name__] = _canonical
