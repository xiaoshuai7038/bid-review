import sys

from app.ai.prompts import store as _canonical

sys.modules[__name__] = _canonical
