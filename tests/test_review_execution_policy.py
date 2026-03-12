from __future__ import annotations

from app.review.execution_policy import ReviewExecutionPolicy, normalize_review_profile


def test_normalize_review_profile_defaults_to_thorough() -> None:
    assert normalize_review_profile("") == "thorough"
    assert normalize_review_profile("unknown") == "thorough"


def test_review_execution_policy_profiles_have_expected_defaults() -> None:
    fast = ReviewExecutionPolicy.for_profile("fast")
    balanced = ReviewExecutionPolicy.for_profile("balanced")
    thorough = ReviewExecutionPolicy.for_profile("thorough")

    assert fast.review_profile == "fast"
    assert balanced.review_profile == "balanced"
    assert thorough.review_profile == "thorough"
    assert fast.enable_second_pass is False
    assert balanced.enable_second_pass is True
    assert thorough.enable_second_pass is True
    assert fast.ocr_filter_policy.min_image_bytes >= balanced.ocr_filter_policy.min_image_bytes
    assert balanced.ocr_filter_policy.min_image_bytes >= thorough.ocr_filter_policy.min_image_bytes
    assert fast.ocr_concurrency.max_inflight_chunks >= thorough.ocr_concurrency.max_inflight_chunks
