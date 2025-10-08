import os
import json
import re
import time
from typing import Optional, List, Dict, Any

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from .models import SearchQuery, SearchResponse, Card, Price, SpecItem, CardLinks
from .filters import hard_filters
from .scoring import score_product

# Carica variabili d’ambiente
load_dotenv(dotenv_path=os.path.join("ops", "env.example"))

app = FastAPI(title="STIGA Product Finder API", version="1.2.0")

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

# --- Live price helpers (cache in-memory) ---
_LIVE_PRICE_CACHE: Dict[str, Dict[str, Any]] = {}  # url -> {"price": int|None, "ts": float}
_LIVE_PRICE_TTL = 60 * 30  # 30 minuti

def _parse_price_eur_from_text(text: str) -> Optional[int]:
    # cerca pattern tipo "2.799 €" / "2799€" / "€ 2.799"
    candidates = []
    for m in re.finditer(r"(?:€\s*)?(\d[\d\.\s]{1,7})(?:\s*€)", text, flags=re.MULTILINE):
        raw = m.group(1)
        num = int(re.sub(r"[^\d]", "", raw)) if raw else None
        if num and 100 <= num <= 20000:
            candidates.append(num)
    return max(candidates) if candidates else None

def _fetch_live_price(url: str) -> Optional[int]:
    try:
        # cache
        c = _LIVE_PRICE_CACHE.get(url)
        if c and (time.time() - c["ts"] < _LIVE_PRICE_TTL):
            return c["price"]

        headers = {"User-Agent": "Mozilla/5.0 (compatible; STIGA-PriceBot/1.0)"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200 or not resp.text:
            _LIVE_PRICE_CACHE[url] = {"price": None, "ts": time.time()}
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        # 1) meta con price (se presente)
        meta = soup.find("meta", attrs={"itemprop": "price"}) or soup.find("meta", attrs={"property": "product:price:amount"})
        if meta and meta.get("content"):
            try:
                price = int(float(meta["content"]))
                _LIVE_PRICE_CACHE[url] = {"price": price, "ts": time.time()}
                return price
            except Exception:
                pass

        # 2) fallback: testo libero con simbolo €
        text = soup.get_text(separator=" ", strip=True)
        price = _parse_price_eur_from_text(text)
        _LIVE_PRICE_CACHE[url] = {"price": price, "ts": time.time()}
        return price
    except Exception:
        _LIVE_PRICE_CACHE[url] = {"price": None, "ts": time.time()}
        return None

# --- Helpers per la Card ---
def build_card(p: Dict[str, Any], score: float) -> Card:
    cov = p.get("coverage_m2", "—")
    slope = p.get("max_slope_pct", "—")
    noise = _noise_value(p)
    perim = _perimeter_label(p.get("perimeter_type", "—"))
    price_val = p.get("price_eur")

    # prezzo formattato
    price_str = "—" if price_val is None else f"{int(price_val):,} €".replace(",", ".")

    # specs essenziali
    specs = [
        SpecItem(label_it="Copertura", label_en="Coverage", value=f"{cov} m²"),
        SpecItem(label_it="Pendenza max", label_en="Max slope", value=f"{slope}%"),
        SpecItem(label_it="Perimetro", label_en="Perimeter", value=perim),
    ]

    # solo PRO (max 3)
    pros: List[str] = []
    if p.get("wireless"): pros.append("Connettività wireless")
    if "rtk" in (p.get("features") or []): pros.append("Precisione RTK")
    if "app" in (p.get("features") or []): pros.append("Controllo da app")
    if noise and noise <= 60: pros.append("Motore silenzioso")
    pros = pros[:3]

    price_obj = Price(label=price_str, note=None)
    links = CardLinks(
        pdp={"label_it": "Vedi scheda prodotto", "label_en": "View product page", "url": p.get("pdp_url")},
        compare={"label_it": "Confronta", "label_en": "Compare", "action": "add_to_compare", "payload": {"id": p.get("id")}},
        lead={"label_it": "Richiedi consulenza", "label_en": "Request consultation", "action": "open_lead_form"}
    )

    # titolo SENZA etichette di punteggio
    title_clean = p.get("name", "")
    subtitle = f"{cov} m² • {slope}% • {perim}"

    return Card(
        title=title_clean,
        subtitle=subtitle,
        image_url=p.get("image_url"),
        price=price_obj,
        specs=specs,
        pros=pros,
        cons=[],              # <-- svantaggi rimossi
        score=round(score, 1),# <-- resta interno per l’ordinamento, ma non lo mostreremo nel testo
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
    limit: int = 5,
    live_price: bool = False
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

    # 1) filtri duri
    filtered = hard_filters(PRODUCTS, q)

    # 2) opzionale: aggiorna prezzi con lettura live dal PDP
    if live_price:
        enriched: List[Dict[str, Any]] = []
        for p in filtered:
            p2 = dict(p)  # copia shallow
            url = p2.get("pdp_url")
            if url:
                lp = _fetch_live_price(url)
                if lp:
                    p2["price_eur"] = lp
            enriched.append(p2)
        filtered = enriched

    # 3) scoring + build card
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
