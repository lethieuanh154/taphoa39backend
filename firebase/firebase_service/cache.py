import time

class Cache:
    def __init__(self):
        self.store = {}

    def set(self, key, value, ttl=300):
        self.store[key] = {"data": value, "expires": time.time() + ttl}

    def get(self, key):
        item = self.store.get(key)
        if item and time.time() < item["expires"]:
            return item["data"]
        self.store.pop(key, None)
        return None

    def has(self, key):
        return self.get(key) is not None

    def invalidate(self, key):
        self.store.pop(key, None)

    def invalidate_prefix(self, prefix):
        """Invalidate all keys starting with prefix."""
        keys_to_remove = [k for k in self.store if k.startswith(prefix)]
        for k in keys_to_remove:
            self.store.pop(k, None)
