import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from models import SearchTarget, AddSearchRequest, AppSettings
from storage import Storage
from ai_engine import AIEngine
from tracker import ConnectionManager, TrackerService

storage = Storage()
env_key = os.environ.get("GEMINI_API_KEY", "").strip()
initial_key = env_key if env_key else storage.settings.gemini_api_key

ai_engine = AIEngine(
    api_key=initial_key,
    model_name=storage.settings.gemini_model
)
ws_manager = ConnectionManager()
tracker = TrackerService(storage, ai_engine, ws_manager)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: start tracker
    tracker.start()
    yield
    # Shutdown: stop tracker
    tracker.stop()

app = FastAPI(title="EasyFlipp Backend", lifespan=lifespan)

# Allow CORS for mobile & web clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("RENDER_EXTERNAL_URL", "192.168.1.104")
    return {
        "app": "EasyFlipp Backend",
        "status": "online",
        "host": host,
        "port": port,
        "searches_count": len(storage.searches),
        "items_count": len(storage.items),
        "coups_de_coeur_count": len(storage.get_coups_de_coeur())
    }

@app.get("/api/host_info")
def get_host_info():
    import socket
    hostname = socket.gethostname()
    local_ip = "192.168.1.104"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass
    return {
        "hostname": hostname,
        "local_ip": local_ip,
        "port": 8000,
        "api_url": f"http://{local_ip}:8000",
        "ws_url": f"ws://{local_ip}:8000/ws"
    }

# --- SEARCHES ENDPOINTS ---

@app.get("/api/searches")
def get_searches():
    return list(storage.searches.values())

@app.post("/api/searches")
async def add_search(req: AddSearchRequest):
    url = req.url.strip()
    platform = ""
    if "vinted" in url.lower():
        platform = "vinted"
    elif "leboncoin" in url.lower():
        platform = "leboncoin"
    else:
        raise HTTPException(
            status_code=400,
            detail="URL non reconnue. Veuillez fournir un lien Vinted ou Leboncoin."
        )

    search = SearchTarget(
        name=req.name.strip() or f"Recherche {platform.capitalize()}",
        platform=platform,
        url=url,
        criteria=req.criteria.strip()
    )
    storage.add_search(search)
    
    # Trigger an immediate poll for this search in background
    asyncio.create_task(tracker._poll_search(search))
    return search

@app.delete("/api/searches/{search_id}")
def delete_search(search_id: str):
    if search_id not in storage.searches:
        raise HTTPException(status_code=404, detail="Recherche introuvable")
    storage.remove_search(search_id)
    return {"success": True}

# --- ITEMS & DEALS ENDPOINTS ---

@app.get("/api/items")
def get_items(limit: int = 100):
    return [it for it in storage.get_items_for_feed(limit=limit) if not it.id.startswith("sim_")]

@app.get("/api/coups_de_coeur")
def get_coups_de_coeur(search_id: str = None):
    return [it for it in storage.get_coups_de_coeur(search_id=search_id) if not it.id.startswith("sim_")]

@app.delete("/api/coups_de_coeur/{item_id}")
def delete_coup_de_coeur(item_id: str):
    if item_id in storage.items:
        storage.items[item_id].matches_criteria = False
        storage.items[item_id].is_best_deal = False
        storage.save_items()
        return {"success": True}
    raise HTTPException(status_code=404, detail="Article introuvable")

@app.post("/api/evaluate_now/{item_id}")
async def evaluate_now(item_id: str):
    if item_id not in storage.items:
        raise HTTPException(status_code=404, detail="Article introuvable")
    item = storage.items[item_id]
    search = storage.searches.get(item.search_id)
    if not search:
        raise HTTPException(status_code=400, detail="Recherche associée inexistante")
    
    asyncio.create_task(tracker._evaluate_item(item, search))
    return {"message": "Évaluation IA lancée en arrière-plan"}

# --- SETTINGS ENDPOINTS ---

@app.get("/api/settings")
def get_settings():
    return storage.settings

@app.post("/api/settings")
def update_settings(new_settings: AppSettings):
    storage.settings = new_settings
    storage.save_settings()
    ai_engine.set_api_key(new_settings.gemini_api_key)
    ai_engine.model_name = new_settings.gemini_model
    return storage.settings

# --- WEBSOCKET ENDPOINT ---

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive & listen for client pings
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
