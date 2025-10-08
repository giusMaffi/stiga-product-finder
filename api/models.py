from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class SearchQuery(BaseModel):
    surface_m2: int = Field(..., ge=1)
    slope_pct: int = Field(..., ge=0)
    perimeter: str = Field("any", pattern="^(virtual|wire|both|any)$")
    budget_band: Optional[str] = Field("any", pattern="^(low|mid|high|any)$")
    noise_pref: Optional[float] = None
    multizone: Optional[bool] = None
    power_source: Optional[str] = Field("any", pattern="^(battery|wire|gasoline|any)$")
    features: Optional[List[str]] = None
    limit: int = 5

class Price(BaseModel):
    label: str
    note: Optional[str] = None

class SpecItem(BaseModel):
    label_it: str
    label_en: str
    value: str

class CardLinks(BaseModel):
    pdp: Dict[str, Any]
    compare: Dict[str, Any]
    lead: Dict[str, Any]

class Card(BaseModel):
    title: str
    subtitle: str
    image_url: Optional[str] = None
    price: Optional[Price] = None
    specs: List[SpecItem]
    pros: List[str]
    cons: List[str]
    score: float
    links: CardLinks

class SearchResponse(BaseModel):
    items: List[Card]
    meta: Dict[str, Any]

