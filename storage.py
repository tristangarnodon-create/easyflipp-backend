import json
import os
from typing import Dict, List, Optional
from models import SearchTarget, ListingItem, AppSettings

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

class Storage:
    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.searches_file = os.path.join(DATA_DIR, "searches.json")
        self.items_file = os.path.join(DATA_DIR, "items.json")
        self.settings_file = os.path.join(DATA_DIR, "settings.json")
        self.seen_ids_file = os.path.join(DATA_DIR, "seen_ids.json")

        self.searches: Dict[str, SearchTarget] = {}
        self.items: Dict[str, ListingItem] = {}
        self.settings: AppSettings = AppSettings()
        self.seen_ids: set = set()

        self.load()

    def load(self):
        # 1. Searches
        if os.path.exists(self.searches_file):
            try:
                with open(self.searches_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for k, v in data.items():
                        self.searches[k] = SearchTarget(**v)
            except Exception as e:
                print(f"[Storage] Error loading searches: {e}")

        # 2. Items
        if os.path.exists(self.items_file):
            try:
                with open(self.items_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for k, v in data.items():
                        if not k.startswith("sim_") and not v.get("id", "").startswith("sim_"):
                            self.items[k] = ListingItem(**v)
            except Exception as e:
                print(f"[Storage] Error loading items: {e}")

        # 3. Settings
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.settings = AppSettings(**data)
            except Exception as e:
                print(f"[Storage] Error loading settings: {e}")

        # 4. Seen IDs
        if os.path.exists(self.seen_ids_file):
            try:
                with open(self.seen_ids_file, "r", encoding="utf-8") as f:
                    self.seen_ids = set(json.load(f))
            except Exception as e:
                print(f"[Storage] Error loading seen_ids: {e}")

    def save_searches(self):
        try:
            with open(self.searches_file, "w", encoding="utf-8") as f:
                data = {k: v.model_dump() for k, v in self.searches.items()}
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Storage] Error saving searches: {e}")

    def save_items(self):
        try:
            with open(self.items_file, "w", encoding="utf-8") as f:
                data = {k: v.model_dump() for k, v in self.items.items()}
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Storage] Error saving items: {e}")

    def save_settings(self):
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(self.settings.model_dump(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Storage] Error saving settings: {e}")

    def save_seen_ids(self):
        try:
            with open(self.seen_ids_file, "w", encoding="utf-8") as f:
                json.dump(list(self.seen_ids), f)
        except Exception as e:
            print(f"[Storage] Error saving seen_ids: {e}")

    def add_search(self, search: SearchTarget):
        self.searches[search.id] = search
        self.save_searches()

    def remove_search(self, search_id: str):
        if search_id in self.searches:
            del self.searches[search_id]
            self.save_searches()

    def add_item(self, item: ListingItem):
        self.items[item.id] = item
        self.seen_ids.add(item.id)
        # Cap items in memory/disk to 500 latest to prevent unbounded growth
        if len(self.items) > 500:
            sorted_keys = sorted(self.items.keys(), key=lambda k: self.items[k].discovered_at)
            # Remove oldest 50 items (except coups de coeur)
            removed = 0
            for k in sorted_keys:
                if not self.items[k].matches_criteria:
                    del self.items[k]
                    removed += 1
                    if removed >= 50:
                        break
        self.save_items()
        self.save_seen_ids()

    def update_item(self, item: ListingItem):
        self.items[item.id] = item
        self.save_items()

    def get_items_for_feed(self, limit: int = 100) -> List[ListingItem]:
        # Sort by discovered_at descending (latest first)
        sorted_list = sorted(self.items.values(), key=lambda x: x.discovered_at, reverse=True)
        return sorted_list[:limit]

    def get_coups_de_coeur(self, search_id: Optional[str] = None) -> List[ListingItem]:
        deals = [it for it in self.items.values() if it.matches_criteria is True]
        if search_id:
            deals = [it for it in deals if it.search_id == search_id]
        # Best deal first, then latest discovered
        return sorted(deals, key=lambda x: (not x.is_best_deal, -x.discovered_at))
