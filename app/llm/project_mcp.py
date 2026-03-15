import sys

from app.ai.mcp import project_config as _canonical

sys.modules[__name__] = _canonical
