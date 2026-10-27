from pydantic import BaseModel, Field
from typing import Optional, List
import time
import uuid

class SearchTarget(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    platform: str  # "vinted" or "leboncoin"
    url: str
    criteria: str = ""
    enabled: bool = True
    created_at: float = Field(default_factory=time.time)

class ListingItem(BaseModel):
    id: str
    search_id: str
    platform: str  # "vinted" or "leboncoin"
    title: str
    price: float
    currency: str = "EUR"
    url: str
    image_urls: List[str] = Field(default_factory=list)
    location: str = ""
    seller_name: str = ""
    seller_rating: Optional[float] = None
    condition: str = ""
    description: str = ""
    published_at: str = ""
    discovered_at: float = Field(default_factory=time.time)
    
    # AI Analysis attributes
    matches_criteria: Optional[bool] = None
    criteria_reason: str = ""
    is_best_deal: bool = False
    is_urgent_deal: bool = False
    urgency_reason: str = ""
    ai_evaluated_at: Optional[float] = None

class AppSettings(BaseModel):
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    poll_interval_seconds: int = 25
    ai_auto_evaluate: bool = True

class AddSearchRequest(BaseModel):
    name: str
    url: str
    criteria: str = ""
