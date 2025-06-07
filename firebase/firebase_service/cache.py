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
