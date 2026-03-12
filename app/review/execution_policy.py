from __future__ import annotations

from dataclasses import dataclass


_VALID_REVIEW_PROFILES = {"fast", "balanced", "thorough"}


@dataclass(frozen=True, slots=True)
class OCRFilterPolicy:
    min_image_bytes: int
    min_image_edge_px: int
    dedup_enabled: bool = True


@dataclass(frozen=True, slots=True)
class OCRConcurrencyPolicy:
    chunk_size: int
    max_inflight_chunks: int


@dataclass(frozen=True, slots=True)
class CachePolicy:
    enabled: bool = True
    reuse_across_runs: bool = True


@dataclass(frozen=True, slots=True)
class ProgressPolicy:
    default_progress_level: str = "agent"
    include_raw_stream_events: bool = False


@dataclass(frozen=True, slots=True)
class RetryBudget:
    json_repair_attempts: int
    completion_retry_attempts: int
    location_retry_attempts: int
    second_pass_attempts: int


@dataclass(frozen=True, slots=True)
class ReviewExecutionPolicy:
    review_profile: str
    enable_second_pass: bool
    enable_completion_retry: bool
    enable_location_retry: bool
    enable_json_repair: bool
    ocr_filter_policy: OCRFilterPolicy
    ocr_concurrency: OCRConcurrencyPolicy
    cache_policy: CachePolicy
    progress_policy: ProgressPolicy
    retry_budget: RetryBudget

    @classmethod
    def for_profile(cls, profile: str | None) -> "ReviewExecutionPolicy":
        normalized = (profile or "thorough").strip().lower()
        if normalized not in _VALID_REVIEW_PROFILES:
            normalized = "thorough"
        if normalized == "fast":
            return cls(
                review_profile="fast",
                enable_second_pass=False,
                enable_completion_retry=True,
                enable_location_retry=True,
                enable_json_repair=True,
                ocr_filter_policy=OCRFilterPolicy(min_image_bytes=512, min_image_edge_px=48, dedup_enabled=True),
                ocr_concurrency=OCRConcurrencyPolicy(chunk_size=24, max_inflight_chunks=6),
                cache_policy=CachePolicy(enabled=True, reuse_across_runs=True),
                progress_policy=ProgressPolicy(default_progress_level="agent", include_raw_stream_events=False),
                retry_budget=RetryBudget(
                    json_repair_attempts=1,
                    completion_retry_attempts=1,
                    location_retry_attempts=1,
                    second_pass_attempts=0,
                ),
            )
        if normalized == "balanced":
            return cls(
                review_profile="balanced",
                enable_second_pass=True,
                enable_completion_retry=True,
                enable_location_retry=True,
                enable_json_repair=True,
                ocr_filter_policy=OCRFilterPolicy(min_image_bytes=256, min_image_edge_px=40, dedup_enabled=True),
                ocr_concurrency=OCRConcurrencyPolicy(chunk_size=20, max_inflight_chunks=5),
                cache_policy=CachePolicy(enabled=True, reuse_across_runs=True),
                progress_policy=ProgressPolicy(default_progress_level="agent", include_raw_stream_events=False),
                retry_budget=RetryBudget(
                    json_repair_attempts=1,
                    completion_retry_attempts=1,
                    location_retry_attempts=1,
                    second_pass_attempts=1,
                ),
            )
        return cls(
            review_profile="thorough",
            enable_second_pass=True,
            enable_completion_retry=True,
            enable_location_retry=True,
            enable_json_repair=True,
            ocr_filter_policy=OCRFilterPolicy(min_image_bytes=128, min_image_edge_px=24, dedup_enabled=True),
            ocr_concurrency=OCRConcurrencyPolicy(chunk_size=16, max_inflight_chunks=4),
            cache_policy=CachePolicy(enabled=True, reuse_across_runs=True),
            progress_policy=ProgressPolicy(default_progress_level="agent", include_raw_stream_events=False),
            retry_budget=RetryBudget(
                json_repair_attempts=1,
                completion_retry_attempts=1,
                location_retry_attempts=1,
                second_pass_attempts=1,
            ),
        )


def normalize_review_profile(profile: str | None) -> str:
    normalized = (profile or "thorough").strip().lower()
    return normalized if normalized in _VALID_REVIEW_PROFILES else "thorough"
