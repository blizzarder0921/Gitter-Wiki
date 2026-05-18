"""
令牌桶速率限制器模块

实现基于令牌桶算法的速率限制，用于控制 GitHub API 请求频率。
仅依赖 Python 标准库（time, threading），无需第三方依赖。

GPLv3 License - Gitter Project
"""

import time
import threading


class TokenBucketRateLimiter:
    """
    令牌桶速率限制器

    令牌桶算法核心思想：
    - 桶中持有一定数量的令牌，每次请求消耗令牌
    - 令牌以固定速率持续补充，直到达到桶容量上限
    - 当桶中令牌不足时，请求被拒绝或需等待

    线程安全：内部使用 threading.Lock 保证多线程环境下令牌分配的一致性。
    时间度量：使用 time.monotonic() 避免系统时钟回拨导致的问题。
    """

    def __init__(self, capacity: float, refill_rate: float):
        """
        初始化令牌桶

        Args:
            capacity: 令牌桶最大容量，即允许突发的最大令牌数
            refill_rate: 令牌补充速率（令牌数/秒），例如 4500/3600 表示每秒补充 1.25 个令牌
        """
        # 桶容量上限
        self._capacity = float(capacity)
        # 令牌补充速率（令牌/秒）
        self._refill_rate = float(refill_rate)
        # 当前可用令牌数，初始化时桶为满
        self._tokens = float(capacity)
        # 上一次补充令牌的时间戳（单调时钟）
        self._last_refill = time.monotonic()
        # 线程锁，保证令牌分配与补充的原子性
        self._lock = threading.Lock()

    def _refill(self):
        """
        根据经过的时间补充令牌

        计算自上次补充以来经过的时间，按补充速率增加令牌数，
        但不超过桶容量上限。此方法需在持有锁的状态下调用。
        """
        now = time.monotonic()
        # 计算时间差（秒）
        elapsed = now - self._last_refill
        # 按速率计算应补充的令牌数
        new_tokens = elapsed * self._refill_rate
        # 补充令牌，不超过容量上限
        self._tokens = min(self._capacity, self._tokens + new_tokens)
        # 更新上次补充时间
        self._last_refill = now

    def acquire(self, tokens: float = 1) -> bool:
        """
        尝试获取令牌（非阻塞）

        如果桶中令牌充足则立即消耗并返回 True，否则返回 False。
        适用于可丢弃请求的场景，如非关键的 API 调用。

        Args:
            tokens: 需要获取的令牌数量，默认为 1

        Returns:
            bool: True 表示获取成功，False 表示令牌不足
        """
        with self._lock:
            # 先补充令牌
            self._refill()
            # 检查令牌是否充足
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def wait_and_acquire(self, tokens: float = 1, timeout: float = 30) -> bool:
        """
        等待并获取令牌（阻塞式）

        如果当前令牌不足，会阻塞等待直到令牌补充充足或超时。
        适用于必须完成的关键请求场景。

        等待策略：采用短间隔轮询（0.1 秒），在持有锁期间检查令牌，
        令牌不足时释放锁等待，避免长时间占用锁导致其他线程饥饿。

        Args:
            tokens: 需要获取的令牌数量，默认为 1
            timeout: 最大等待时间（秒），默认 30 秒

        Returns:
            bool: True 表示在超时前成功获取令牌，False 表示超时未获取
        """
        # 记录等待开始时间
        deadline = time.monotonic() + timeout
        # 轮询间隔（秒）
        poll_interval = 0.1

        while True:
            with self._lock:
                # 补充令牌
                self._refill()
                # 检查令牌是否充足
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True

            # 检查是否超时
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False

            # 等待较短时间后重试，避免忙等待消耗 CPU
            time.sleep(min(poll_interval, remaining))

    @property
    def available_tokens(self) -> float:
        """
        获取当前可用令牌数

        此属性会先补充令牌再返回结果，确保返回值反映最新状态。

        Returns:
            float: 当前可用令牌数
        """
        with self._lock:
            self._refill()
            return self._tokens

    @property
    def capacity(self) -> float:
        """
        获取令牌桶容量上限

        Returns:
            float: 令牌桶容量
        """
        return self._capacity

    @property
    def refill_rate(self) -> float:
        """
        获取令牌补充速率

        Returns:
            float: 补充速率（令牌/秒）
        """
        return self._refill_rate


# ============================================================
# 全局速率限制器实例
# ============================================================

# GitHub 认证用户速率限制器
# 官方限制：5000 请求/小时，此处保守设为 4500 请求/小时
# 补充速率：4500 / 3600 = 1.25 令牌/秒
github_rate_limiter = TokenBucketRateLimiter(
    capacity=4500,
    refill_rate=4500 / 3600
)

# GitHub 未认证用户速率限制器
# 官方限制：60 请求/小时，此处保守设为 50 请求/小时
# 补充速率：50 / 3600 ≈ 0.0139 令牌/秒
github_rate_limiter_unauth = TokenBucketRateLimiter(
    capacity=50,
    refill_rate=50 / 3600
)


def get_github_rate_limiter(token: str = None) -> TokenBucketRateLimiter:
    """
    根据是否提供 token 返回对应的 GitHub 速率限制器实例

    提供有效的 GitHub Token 时返回认证用户的限制器（更高配额），
    未提供时返回未认证用户的限制器（较低配额）。

    Args:
        token: GitHub 个人访问令牌，为 None 或空字符串时视为未认证

    Returns:
        TokenBucketRateLimiter: 对应的速率限制器实例
    """
    if token:
        return github_rate_limiter
    return github_rate_limiter_unauth
