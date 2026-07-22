"""
限流器 — 基于内存的令牌桶。
支持按 api_key_id 和 user_id 两种维度限流。
P0 简单实现，P3 可升级为 Redis 分布式版本。
"""
import time
import threading
from typing import Dict, Tuple, Union
from server.config import RATE_LIMIT_PER_KEY, RATE_LIMIT_WINDOW


class TokenBucket:
    """简单的令牌桶：每个窗口 {capacity} 次"""
    def __init__(self, capacity: int, window_seconds: float):
        self.capacity = capacity
        self.window = window_seconds
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()

    def consume(self, tokens: int = 1) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        # 按时间比例补充令牌
        refill = elapsed * (self.capacity / self.window)
        self.tokens = min(self.capacity, self.tokens + refill)
        self.last_refill = now

        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False


class RateLimiter:
    """按 api_key_id 或 user_id 存储令牌桶的限流器"""

    def __init__(self, capacity: int = RATE_LIMIT_PER_KEY, window: float = RATE_LIMIT_WINDOW):
        self.capacity = capacity
        self.window = window
        self._buckets: Dict[int, TokenBucket] = {}
        self._user_buckets: Dict[int, TokenBucket] = {}
        self._lock = threading.Lock()

    def _get_or_create_bucket(self, store: Dict[int, TokenBucket], key: int) -> TokenBucket:
        bucket = store.get(key)
        if bucket is None or bucket.capacity != self.capacity:
            bucket = TokenBucket(self.capacity, self.window)
            store[key] = bucket
        return bucket

    def is_allowed(self, api_key_id: int) -> Tuple[bool, float]:
        """
        按 api_key_id 限流。
        返回 (是否允许, 还需等待的秒数)。
        """
        with self._lock:
            bucket = self._get_or_create_bucket(self._buckets, api_key_id)
            if bucket.consume(1):
                return True, 0.0
            wait_time = self.window / self.capacity
            return False, round(wait_time, 1)

    def is_allowed_by_user(self, user_id: int) -> Tuple[bool, float]:
        """
        按 user_id 限流（IM 用户无 API Key 时使用）。
        返回 (是否允许, 还需等待的秒数)。
        """
        with self._lock:
            bucket = self._get_or_create_bucket(self._user_buckets, user_id)
            if bucket.consume(1):
                return True, 0.0
            wait_time = self.window / self.capacity
            return False, round(wait_time, 1)

    def cleanup(self, max_idle_seconds: float = 300):
        """清理闲置超过 max_idle_seconds 的桶（可定时调用）"""
        now = time.monotonic()
        with self._lock:
            for store in (self._buckets, self._user_buckets):
                stale = [
                    k for k, b in store.items()
                    if now - b.last_refill > max_idle_seconds
                ]
                for k in stale:
                    del store[k]


# 全局单例
_limiter = RateLimiter()


def get_limiter() -> RateLimiter:
    return _limiter
