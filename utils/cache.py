# utils/cache.py
import time
from typing import Any, Optional
from threading import Lock


class SimpleCache:
    """Thread-safe in-memory cache"""

    def __init__(self):
        self.data = {}
        self.lock = Lock()

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        with self.lock:
            if key in self.data:
                value, expires_at = self.data[key]
                if time.time() < expires_at:
                    return value
                else:
                    del self.data[key]
        return None

    def set(self, key: str, value: Any, ttl: int = 300):
        """Set value with TTL (seconds)"""
        with self.lock:
            self.data[key] = (value, time.time() + ttl)

    def delete(self, key: str):
        """Delete key"""
        with self.lock:
            self.data.pop(key, None)

    def clear(self):
        """Clear all cache"""
        with self.lock:
            self.data.clear()


# Global cache instance
cache = SimpleCache()
