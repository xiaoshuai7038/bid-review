import sys

from app.review.workflows import legacy_engine as _canonical

sys.modules[__name__] = _canonical
