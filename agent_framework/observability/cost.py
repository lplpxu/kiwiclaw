"""Cost Control Module

Provides token budget management and cost tracking for LLM API calls.
[PHASE12] Agent组件 - CostTracker/TokenBudget
"""

import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum
import threading

# Debug print helper
def _debug(msg: str):
    print(f"[PHASE12] [CostTracker] {msg}")


class BudgetExceededAction(Enum):
    """Action to take when budget is exceeded"""
    WARN = "warn"           # Just warn, continue
    BLOCK = "block"         # Block the request
    COMPACT = "compact"     # Trigger compaction
    STOP = "stop"          # Stop execution


class Provider(Enum):
    """LLM Provider"""
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOOGLE = "google"
    OTHER = "other"


# Provider pricing (per 1M tokens as of 2024)
# Input pricing, Output pricing
PROVIDER_PRICING = {
    Provider.ANTHROPIC: {
        "claude-sonnet-4-20250514": (3.0, 15.0),  # Input $, Output $
        "claude-opus-4-20250514": (15.0, 75.0),
        "claude-haiku-4-20250514": (0.25, 1.25),
    },
    Provider.OPENAI: {
        "gpt-4o": (2.5, 10.0),
        "gpt-4o-mini": (0.15, 0.60),
        "gpt-4-turbo": (10.0, 30.0),
    },
    Provider.GOOGLE: {
        "gemini-1.5-pro": (1.25, 5.0),
        "gemini-1.5-flash": (0.075, 0.30),
    },
}


@dataclass
class TokenBudget:
    """Token budget for controlling API usage

    Tracks per-turn and per-session token limits.
    """
    # Per-turn limits
    per_turn_limit: int = 100000      # Max tokens per single LLM call
    per_session_limit: int = 1000000  # Max tokens per session

    # Warning thresholds (as fraction of limit)
    warning_threshold: float = 0.8    # Warn at 80%
    block_threshold: float = 1.0       # Block at 100%

    # Current usage
    _per_turn_used: int = 0
    _per_session_used: int = 0
    _last_reset: float = field(default_factory=time.time)

    def __post_init__(self):
        self._lock = threading.Lock()

    @property
    def per_turn_remaining(self) -> int:
        return max(0, self.per_turn_limit - self._per_turn_used)

    @property
    def per_session_remaining(self) -> int:
        return max(0, self.per_session_limit - self._per_session_used)

    @property
    def per_turn_usage_fraction(self) -> float:
        if self.per_turn_limit == 0:
            return 0.0
        return self._per_turn_used / self.per_turn_limit

    @property
    def per_session_usage_fraction(self) -> float:
        if self.per_session_limit == 0:
            return 0.0
        return self._per_session_used / self.per_session_limit

    def check_per_turn(self, tokens: int) -> tuple[bool, str]:
        """Check if per-turn token usage is within budget

        Returns:
            (allowed, message)
        """
        with self._lock:
            new_usage = self._per_turn_used + tokens
            fraction = new_usage / self.per_turn_limit if self.per_turn_limit > 0 else 0

            if fraction >= self.block_threshold:
                return False, f"Per-turn budget exceeded: {new_usage}/{self.per_turn_limit}"

            if fraction >= self.warning_threshold:
                return True, f"Per-turn budget warning: {new_usage}/{self.per_turn_limit} ({fraction:.0%})"

            return True, ""

    def check_per_session(self, tokens: int) -> tuple[bool, str]:
        """Check if per-session token usage is within budget

        Returns:
            (allowed, message)
        """
        with self._lock:
            new_usage = self._per_session_used + tokens
            fraction = new_usage / self.per_session_limit if self.per_session_limit > 0 else 0

            if fraction >= self.block_threshold:
                return False, f"Per-session budget exceeded: {new_usage}/{self.per_session_limit}"

            if fraction >= self.warning_threshold:
                return True, f"Per-session budget warning: {new_usage}/{self.per_session_limit} ({fraction:.0%})"

            return True, ""

    def record_usage(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Record token usage"""
        with self._lock:
            total = prompt_tokens + completion_tokens
            self._per_turn_used += total
            self._per_session_used += total

    def reset_per_turn(self) -> None:
        """Reset per-turn counter"""
        with self._lock:
            self._per_turn_used = 0

    def reset_session(self) -> None:
        """Reset session counters"""
        with self._lock:
            self._per_turn_used = 0
            self._per_session_used = 0
            self._last_reset = time.time()

    def to_dict(self) -> dict:
        return {
            "per_turn_limit": self.per_turn_limit,
            "per_turn_used": self._per_turn_used,
            "per_turn_remaining": self.per_turn_remaining,
            "per_turn_usage_fraction": self.per_turn_usage_fraction,
            "per_session_limit": self.per_session_limit,
            "per_session_used": self._per_session_used,
            "per_session_remaining": self.per_session_remaining,
            "per_session_usage_fraction": self.per_session_usage_fraction,
        }


@dataclass
class CostRecord:
    """Record of a single cost event"""
    timestamp: float
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost: float
    currency: str = "USD"
    metadata: Dict[str, Any] = field(default_factory=dict)


class CostTracker:
    """Tracks LLM API costs

    Tracks token usage and calculates costs based on provider pricing.
    """

    def __init__(self):
        self._records: List[CostRecord] = []
        self._lock = threading.Lock()

        # Budget
        self.budget = TokenBudget()

        # Cost limits
        self.per_session_cost_limit: float = 10.0  # $10 per session
        self.warning_threshold: float = 0.8         # Warn at 80%

        # Accumulated cost
        self._total_cost: float = 0.0

    def get_provider(self, model: str) -> Provider:
        """Determine provider from model name"""
        model_lower = model.lower()
        if "claude" in model_lower:
            return Provider.ANTHROPIC
        elif "gpt" in model_lower or "openai" in model_lower:
            return Provider.OPENAI
        elif "gemini" in model_lower:
            return Provider.GOOGLE
        return Provider.OTHER

    def get_pricing(self, provider: Provider, model: str) -> tuple[float, float]:
        """Get pricing for a model (returns (input_price, output_price) per 1M tokens)"""
        if provider in PROVIDER_PRICING:
            if model in PROVIDER_PRICING[provider]:
                return PROVIDER_PRICING[provider][model]

        # Default pricing for unknown models
        return (1.0, 5.0)

    def calculate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str,
    ) -> float:
        """Calculate cost for token usage"""
        provider = self.get_provider(model)
        input_price, output_price = self.get_pricing(provider, model)

        prompt_cost = (prompt_tokens / 1_000_000) * input_price
        completion_cost = (completion_tokens / 1_000_000) * output_price

        return prompt_cost + completion_cost

    def record(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str,
        metadata: Dict[str, Any] = None,
    ) -> CostRecord:
        """Record a cost event"""
        _debug(f"→ record(prompt={prompt_tokens}, completion={completion_tokens}, model={model})")
        cost = self.calculate_cost(prompt_tokens, completion_tokens, model)

        record = CostRecord(
            timestamp=time.time(),
            provider=self.get_provider(model).value,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost=cost,
            metadata=metadata or {},
        )

        with self._lock:
            self._records.append(record)
            self._total_cost += cost

        # Also record in budget
        self.budget.record_usage(prompt_tokens, completion_tokens)

        print(f"[DEBUG cost] Recorded: {model} | prompt={prompt_tokens}, completion={completion_tokens}, cost=${cost:.4f}")

        return record

    def check_budget(self, prompt_tokens: int, completion_tokens: int) -> tuple[bool, str]:
        """Check if a new request would exceed budget

        Returns:
            (allowed, message)
        """
        total_tokens = prompt_tokens + completion_tokens

        # Check per-turn
        allowed, msg = self.budget.check_per_turn(total_tokens)
        if not allowed:
            return False, f"[BUDGET] {msg}"

        # Check per-session
        allowed, msg = self.budget.check_per_session(total_tokens)
        if not allowed:
            return False, f"[BUDGET] {msg}"

        # Check cost limit
        projected_cost = self.calculate_cost(
            prompt_tokens,
            completion_tokens,
            "claude-sonnet-4-20250514"  # Use default model for projection
        )

        if self._total_cost + projected_cost > self.per_session_cost_limit:
            return False, f"[BUDGET] Session cost limit exceeded: ${self._total_cost + projected_cost:.2f}/${self.per_session_cost_limit}"

        if self._total_cost + projected_cost > self.per_session_cost_limit * self.warning_threshold:
            return True, f"[BUDGET] Cost warning: ${self._total_cost + projected_cost:.2f}/${self.per_session_cost_limit}"

        return True, ""

    def get_total_cost(self) -> float:
        """Get total accumulated cost"""
        with self._lock:
            return self._total_cost

    def get_total_tokens(self) -> tuple[int, int]:
        """Get total prompt and completion tokens"""
        with self._lock:
            prompt_total = sum(r.prompt_tokens for r in self._records)
            completion_total = sum(r.completion_tokens for r in self._records)
            return prompt_total, completion_total

    def get_recent_records(self, limit: int = 10) -> List[CostRecord]:
        """Get recent cost records"""
        with self._lock:
            return self._records[-limit:]

    def get_cost_summary(self) -> dict:
        """Get cost summary"""
        with self._lock:
            if not self._records:
                return {
                    "total_cost": 0.0,
                    "total_prompt_tokens": 0,
                    "total_completion_tokens": 0,
                    "record_count": 0,
                    "average_cost_per_call": 0.0,
                }

            return {
                "total_cost": self._total_cost,
                "total_prompt_tokens": sum(r.prompt_tokens for r in self._records),
                "total_completion_tokens": sum(r.completion_tokens for r in self._records),
                "record_count": len(self._records),
                "average_cost_per_call": self._total_cost / len(self._records),
                "budget": self.budget.to_dict(),
            }

    def reset(self) -> None:
        """Reset all tracking"""
        with self._lock:
            self._records.clear()
            self._total_cost = 0.0
        self.budget.reset_session()


class RateLimiter:
    """Rate limiter for API calls

    Implements token bucket algorithm for rate limiting.
    [PHASE12] Agent组件 - RateLimiter
    """

    def __init__(
        self,
        requests_per_minute: int = 60,
        requests_per_day: int = 10000,
    ):
        self.requests_per_minute = requests_per_minute
        self.requests_per_day = requests_per_day

        self._minute_bucket: float = float(requests_per_minute)
        self._day_bucket: float = float(requests_per_day)
        self._last_minute_refill = time.time()
        self._last_day_refill = time.time()
        self._lock = threading.Lock()
        _debug(f"RateLimiter initialized: {requests_per_minute}/min, {requests_per_day}/day")

    def _refill(self) -> None:
        """Refill buckets based on elapsed time"""
        now = time.time()
        elapsed_minute = now - self._last_minute_refill
        elapsed_day = now - self._last_day_refill

        # Refill minute bucket (refill rate = requests_per_minute per second)
        if elapsed_minute >= 1.0:
            self._minute_bucket = min(
                self.requests_per_minute,
                self._minute_bucket + elapsed_minute * self.requests_per_minute / 60.0
            )
            self._last_minute_refill = now

        # Refill day bucket
        if elapsed_day >= 1.0:
            self._day_bucket = min(
                self.requests_per_day,
                self._day_bucket + elapsed_day * self.requests_per_day / 86400.0
            )
            self._last_day_refill = now

    def check(self) -> tuple[bool, str]:
        """Check if a request is allowed

        Returns:
            (allowed, message)
        """
        with self._lock:
            self._refill()

            if self._minute_bucket < 1.0:
                wait_time = (1.0 - self._minute_bucket) * 60.0 / self.requests_per_minute
                return False, f"Rate limit: minute bucket empty, wait {wait_time:.1f}s"

            if self._day_bucket < 1.0:
                return False, "Rate limit: daily limit exceeded"

            return True, ""

    def consume(self) -> None:
        """Consume one request from the bucket"""
        with self._lock:
            self._refill()
            self._minute_bucket -= 1.0
            self._day_bucket -= 1.0

    def wait_time(self) -> float:
        """Get estimated wait time until next request is allowed"""
        with self._lock:
            self._refill()
            if self._minute_bucket >= 1.0:
                return 0.0
            return (1.0 - self._minute_bucket) * 60.0 / self.requests_per_minute


# Global instances
_cost_tracker: Optional[CostTracker] = None
_rate_limiter: Optional[RateLimiter] = None


def get_cost_tracker() -> CostTracker:
    """Get the global cost tracker"""
    global _cost_tracker
    if _cost_tracker is None:
        _cost_tracker = CostTracker()
    return _cost_tracker


def get_rate_limiter() -> RateLimiter:
    """Get the global rate limiter"""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter
