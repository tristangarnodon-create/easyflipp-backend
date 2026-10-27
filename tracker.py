import asyncio
import time
from typing import Set, List
from fastapi import WebSocket
from models import ListingItem, SearchTarget
from storage import Storage
from scrapers.vinted import VintedScraper
from scrapers.leboncoin import LeboncoinScraper
from ai_engine import AIEngine

class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        print(f"[WS] Client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            print(f"[WS] Client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        if not self.active_connections:
            return
        dead = []
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for d in dead:
            self.disconnect(d)

class TrackerService:
    def __init__(self, storage: Storage, ai_engine: AIEngine, ws_manager: ConnectionManager):
        self.storage = storage
        self.ai_engine = ai_engine
        self.ws_manager = ws_manager
        self.vinted_scraper = VintedScraper()
        self.leboncoin_scraper = LeboncoinScraper()
        self.is_running = False
        self._task = None

    def start(self):
        if not self.is_running:
            self.is_running = True
            self._task = asyncio.create_task(self._poll_loop())
            print("[TrackerService] Started tracking loop.")

    def stop(self):
        self.is_running = False
        if self._task:
            self._task.cancel()

    async def _poll_loop(self):
        while self.is_running:
            try:
                active_searches = [s for s in self.storage.searches.values() if s.enabled]
                for search in active_searches:
                    await self._poll_search(search)
                    await asyncio.sleep(2)
            except Exception as e:
                print(f"[TrackerService] Error in loop: {e}")

            interval = max(15, self.storage.settings.poll_interval_seconds)
            await asyncio.sleep(interval)

    async def _poll_search(self, search: SearchTarget):
        try:
            if search.platform == "vinted":
                listings = await asyncio.to_thread(self.vinted_scraper.fetch_listings, search.url, search.id)
            elif search.platform == "leboncoin":
                listings = await asyncio.to_thread(self.leboncoin_scraper.fetch_listings, search.url, search.id)
            else:
                return

            new_items: List[ListingItem] = []
            for item in listings:
                if item.id not in self.storage.seen_ids:
                    self.storage.add_item(item)
                    new_items.append(item)

            if new_items:
                print(f"[TrackerService] Found {len(new_items)} new items for search: {search.name}")
                # Dispatch IMMEDIATELY to live feed (< 1 min)
                for item in new_items:
                    await self.ws_manager.broadcast({
                        "type": "new_item",
                        "search_id": search.id,
                        "search_name": search.name,
                        "item": item.model_dump()
                    })

                    # Schedule AI analysis in background
                    if search.criteria.strip() and self.storage.settings.ai_auto_evaluate:
                        asyncio.create_task(self._evaluate_item(item, search))

        except Exception as e:
            print(f"[TrackerService] Error polling search {search.name}: {e}")

    async def _evaluate_item(self, item: ListingItem, search: SearchTarget):
        try:
            matches, reason, is_urgent, urgency_reason = await self.ai_engine.evaluate_listing(item, search.criteria)
            item.matches_criteria = matches
            item.criteria_reason = reason
            item.is_urgent_deal = is_urgent
            item.urgency_reason = urgency_reason
            item.ai_evaluated_at = time.time()
            self.storage.update_item(item)

            if matches:
                print(f"[TrackerService] AI MATCH! '{item.title}' matches all criteria for {search.name}")

                # Re-arbitrate best deal for this search
                qualifying_items = self.storage.get_coups_de_coeur(search_id=search.id)
                best_id, best_reason = await self.ai_engine.select_best_deal(qualifying_items, search.criteria)

                for q in qualifying_items:
                    is_best = (q.id == best_id)
                    if q.is_best_deal != is_best:
                        q.is_best_deal = is_best
                        if is_best and best_reason:
                            q.criteria_reason = f"⭐ Coup de cœur ultime : {best_reason}"
                        self.storage.update_item(q)

                # Broadcast immediate deal matched event
                updated_item = self.storage.items.get(item.id, item)
                await self.ws_manager.broadcast({
                    "type": "deal_matched",
                    "search_id": search.id,
                    "search_name": search.name,
                    "best_deal_id": best_id,
                    "item": updated_item.model_dump()
                })
            else:
                await self.ws_manager.broadcast({
                    "type": "item_evaluated",
                    "item_id": item.id,
                    "matches_criteria": False,
                    "reason": reason
                })

        except Exception as e:
            print(f"[TrackerService] Error in AI evaluation: {e}")
