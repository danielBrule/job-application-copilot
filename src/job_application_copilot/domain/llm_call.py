"""Domain values and aggregate read models for token-bearing LLM calls."""

from dataclasses import dataclass
from enum import StrEnum


class LlmCallStatus(StrEnum):
    """Application outcome of one provider invocation."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class LlmFailureCategory(StrEnum):
    """Safe, controlled failure categories that never contain provider response text."""

    TIMEOUT = "TIMEOUT"
    RATE_LIMIT = "RATE_LIMIT"
    NETWORK = "NETWORK"
    PROVIDER = "PROVIDER"
    INCOMPLETE_RESPONSE = "INCOMPLETE_RESPONSE"
    SCHEMA_VALIDATION = "SCHEMA_VALIDATION"
    INTERRUPTED = "INTERRUPTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class LlmUsageTotals:
    """Aggregated usage and duration for one job and optional operation."""

    call_count: int
    succeeded_count: int
    failed_count: int
    calls_with_usage: int
    input_tokens: int
    cached_input_tokens: int
    cache_write_tokens: int
    output_tokens: int
    reasoning_tokens: int
    total_tokens: int
    duration_seconds: float
