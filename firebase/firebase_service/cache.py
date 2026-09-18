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

    def update_item_in_lists(self, prefix, item_id_field, item_id, updated_data):
        """
        Update a single item inside all cached lists matching prefix.
        Instead of invalidating the entire list, patch the item in-place.

        Args:
            prefix: Cache key prefix to match (e.g. "all_products:")
            item_id_field: Field name used as ID (e.g. "Id")
            item_id: The ID value to find
            updated_data: Dict of fields to merge into the item
        """
        item_id_str = str(item_id)
        for key, entry in list(self.store.items()):
            if not key.startswith(prefix):
                continue
            if time.time() >= entry["expires"]:
                self.store.pop(key, None)
                continue
            data = entry["data"]
            if not isinstance(data, list):
                continue
            for i, item in enumerate(data):
                if str(item.get(item_id_field)) == item_id_str:
                    data[i] = {**item, **updated_data}
                    break

    def bulk_update_items_in_lists(self, prefix, item_id_field, updates_by_id):
        """Patch NHIEU item cung luc trong moi list cache khop prefix, duyet list DUNG 1 LAN.

        Goi update_item_in_lists() trong vong lap se duyet lai ca list cho tung san pham
        (hoa don 20 mon x 15k SP = 300k vong). Ham nay tra ve so item da patch.

        Args:
            updates_by_id: {str(item_id): {field: value}}
        """
        if not updates_by_id:
            return 0
        patched = 0
        for key, entry in list(self.store.items()):
            if not key.startswith(prefix):
                continue
            if time.time() >= entry["expires"]:
                self.store.pop(key, None)
                continue
            data = entry["data"]
            if not isinstance(data, list):
                continue
            for i, item in enumerate(data):
                upd = updates_by_id.get(str(item.get(item_id_field)))
                if upd:
                    data[i] = {**item, **upd}
                    patched += 1
        return patched

    def remove_item_from_lists(self, prefix, item_id_field, item_id):
        """
        Remove a single item from all cached lists matching prefix.

        Args:
            prefix: Cache key prefix to match (e.g. "all_products:")
            item_id_field: Field name used as ID (e.g. "Id")
            item_id: The ID value to remove
        """
        item_id_str = str(item_id)
        for key, entry in list(self.store.items()):
            if not key.startswith(prefix):
                continue
            if time.time() >= entry["expires"]:
                self.store.pop(key, None)
                continue
            data = entry["data"]
            if not isinstance(data, list):
                continue
            entry["data"] = [item for item in data if str(item.get(item_id_field)) != item_id_str]

    def add_item_to_lists(self, prefix, item):
        """
        Add an item to all cached lists matching prefix.

        Args:
            prefix: Cache key prefix to match (e.g. "all_products:")
            item: The item dict to add
        """
        for key, entry in list(self.store.items()):
            if not key.startswith(prefix):
                continue
            if time.time() >= entry["expires"]:
                self.store.pop(key, None)
                continue
            data = entry["data"]
            if not isinstance(data, list):
                continue
            data.append(item)
