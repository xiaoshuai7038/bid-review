from app.review.workflows.legacy_engine import (
    detect_roles_with_claude,
    detect_tender_and_bids_with_claude,
)

detect_roles = detect_roles_with_claude
detect_tender_and_bids = detect_tender_and_bids_with_claude

__all__ = [
    "detect_roles",
    "detect_tender_and_bids",
    "detect_roles_with_claude",
    "detect_tender_and_bids_with_claude",
]
