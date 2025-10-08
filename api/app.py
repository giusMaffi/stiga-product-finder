import os
import json
import uuid
from typing import Optional, List, Dict, Any

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from .models import SearchQuery, SearchResponse, Card, Price, SpecItem, CardLinks
from .filters import hard_filters
from .scoring import score_product

# Carica variabili d’ambiente
load_dotenv(dotenv_path=os.path.join("ops", "env.example"))

app = FastAPI(title="STIGA Product Finder API", version="1.0.0")

# --- CORS ---
origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Caricamento dati ---
PRODUCTS: List[Dict[str, Any]] = []

@app.on_event("startup")
def load_data():
    """Carica i prodotti e scarta quelli con PDP fuori dal dominio STIGA."""
    global PRODUCTS
    data_path = os.path.join("data", "products.json")
    if not os.path.exists(data_path):
        print("⚠️  File data/products.json non trovato.")
        PRODUCTS = []
        return
    with open(data_path, "r") as f:
        raw = json.load(f)

    allowed_domains = ("https://www.stiga.com", "https://stiga.com")
    PRODUCTS = []
    skipped = 0
    for p in raw:
        pdp = p.get("pdp_url", "")
        if not any(pdp.startswith(dom) for dom in allowed_domains):
            skipped += 1
            continue
        PRODUCTS.append(p)
    print(f"✅ Caricati {len(PRODUCTS)} prodotti (scartati {skipped} non-STIGA)")

# --- Helpers per la Card ---
def _noise_value(p: Dict[str, Any]) -> Optional[float]:
    snd = p.get("sound") or {}
    return snd.get("lwa_measured_db", snd.get("lwa_guaranteed_db"))

def _perimeter_label(perimeter_type: str) -> str:
    mapping = {"virtual": "Virtuale", "wire": "Filo", "both": "Virtuale/Filo"}
    return mapping.get(perimeter_type, perimeter_type)

def _power_label(power: str) -> str:
    mapping = {"battery": "Batteria", "wire": "Filo", "gasoline": "Benzina"}
    return mapping.get(power, power)

def build_card(p: Dict[str, Any], score: float) -> Card:
    cov = p.get("coverage_m2", "—")
    slope = p.get("max_slope_pct", "—")
    noise = _noise_value(p)
    perim = _perimeter_label(p.get("perimeter_type", "—"))
    power = _power_label(p.get("power_source", "—"))
    price = p.get("price_eur")

    specs = [
        SpecItem(label_it="Copertura", label_en="Coverage", value=f"{cov} m²"),
        SpecItem(label_it="Pendenza max", label_en="Max slope", value=f"{slope}%"),
        SpecItem(label_it="Perimetro", label_en="Perimeter", value=perim),
        SpecItem(label_it="Rumorosità", label_en="Noise", value=f"{noise} dB(A)" if noise else "—"),
        SpecItem(label_it="Alimentazione", label_en="Power source", value=power),
    ]

    pros = []
    cons = []

    if p.get("wireless"): pros.append("Connettività wireless")
    if "rtk" in (p.get("features") or []): pros.append("Precisione RTK")
    if "app" in (p.get("features") or []): pros.append("Controllo da app")
    if "antitheft" in (p.get("features") or []): pros.append("Sistema antifurto")
    if noise and noise <= 60: pros.append("Motore silenzioso")

    if price and price > 1500: cons.append("Prezzo superiore alla media")
    cons.append("Richiede settaggio iniziale")

    price_obj = Price(label=f"{int(price)} €" if price else "—", note="Prezzo indicativo")
    links = CardLinks(
        pdp={"label_it": "Vedi scheda prodotto", "label_en": "View product page", "url": p.get("pdp_url")},
        compare={"label_it": "Confronta", "label_en": "Compare", "action": "add_to_compare"},
        lead={"label_it": "Richiedi consulenza", "label_en": "Request consultation", "action": "open_lead_form"}
    )

    subtitle = f"Perfetto per giardini fino a {cov} m² con pendenza {slope}%"

    return Card(
        title=p.get("name", ""),
        subtitle=subtitle,
        image_url=p.get("image_url"),
        price=price_obj,
        specs=specs,
        pros=pros,
        cons=cons,
        score=round(score, 1),
        links=links
    )

# --- Endpoint base ---
@app.get("/health")
def health():
    return {"status": "ok", "env": os.getenv("ENV", "unknown"), "products_loaded": len(PRODUCTS)}

@app.get("/products/all")
def list_products():
    return {"count": len(PRODUCTS), "items": PRODUCTS}

# --- /products/search ---
@app.get("/products/search", response_model=SearchResponse)
def search_products(
    surface_m2: int,
    slope_pct: int,
    perimeter: str = "any",
    budget_band: str = "any",
    noise_pref: Optional[float] = None,
    multizone: Optional[bool] = None,
    power_source: str = "any",
    features: Optional[str] = Query(None, description="CSV es: rtk,app,wireless"),
    limit: int = 5
):
    q = SearchQuery(
        surface_m2=surface_m2,
        slope_pct=slope_pct,
        perimeter=perimeter,
        budget_band=budget_band,
        noise_pref=noise_pref,
        multizone=multizone,
        power_source=power_source,
        features=[f.strip() for f in features.split(",")] if features else None,
        limit=limit
    )

    filtered = hard_filters(PRODUCTS, q)
    scored = [(p, score_product(p, q)) for p in filtered]
    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:q.limit]
    cards = [build_card(p, s) for p, s in top]

    meta = {
        "total": len(filtered),
        "limit": q.limit,
        "filters_applied": q.dict()
    }

    return SearchResponse(items=cards, meta=meta)
