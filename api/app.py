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

app = FastAPI(title="STIGA Product Finder API", version="1.4.0")

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

# -----------------------------
#       LIVE ENRICHMENT
# -----------------------------
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; STIGA-ProductFinder/1.0)"}

# cache
_LIVE_PRICE_CACHE: Dict[str, Dict[str, Any]] = {}   # url -> {"price": int|None, "ts": float}
_LIVE_IMAGE_CACHE: Dict[str, Dict[str, Any]] = {}   # url -> {"image": str|None, "ts": float}
_TTL_PRICE = 60 * 30   # 30 minuti
_TTL_IMAGE = 60 * 60   # 60 minuti

def _get_soup(url: str) -> Optional[BeautifulSoup]:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=12, allow_redirects=True)
        if resp.status_code >= 400 or not resp.text:
            return None
        return BeautifulSoup(resp.text, "html.parser")
    except Exception:
        return None

def _parse_jsonld_price_and_image(soup: BeautifulSoup) -> Dict[str, Optional[Any]]:
    out: Dict[str, Optional[Any]] = {"price": None, "image": None}
    try:
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string.strip()) if tag.string else None
            except Exception:
                continue
            if not data:
                continue
            # JSON-LD può essere lista o oggetto
            candidates = data if isinstance(data, list) else [data]
            for obj in candidates:
                if not isinstance(obj, dict):
                    continue
                # cerca schema Product
                if obj.get("@type") == "Product":
                    # image
                    img = obj.get("image")
                    if isinstance(img, list) and img:
                        out["image"] = img[0]
                    elif isinstance(img, str):
                        out["image"] = img
                    # price
                    offers = obj.get("offers")
                    if isinstance(offers, dict):
                        price = offers.get("price") or offers.get("lowPrice")
                        if isinstance(price, (int, float, str)):
                            try:
                                out["price"] = int(float(str(price)))
                            except Exception:
                                pass
                # fallback: oggetti con "offers" anche senza @type preciso
                if not out["price"] and isinstance(obj.get("offers"), dict):
                    price = obj["offers"].get("price") or obj["offers"].get("lowPrice")
                    if isinstance(price, (int, float, str)):
                        try:
                            out["price"] = int(float(str(price)))
                        except Exception:
                            pass
    except Exception:
        pass
    return out

def _parse_price_from_text(text: str) -> Optional[int]:
    # pattern: "2.799 €" / "2799€" / "€ 2.799"
    candidates = []
    for m in re.finditer(r"(?:€\s*)?(\d[\d\.\s]{1,7})(?:\s*€)", text, flags=re.MULTILINE):
        raw = m.group(1)
        num = int(re.sub(r"[^\d]", "", raw)) if raw else None
        if num and 100 <= num <= 20000:
            candidates.append(num)
    return max(candidates) if candidates else None

def _fetch_live_price(url: str) -> Optional[int]:
    # cache
    c = _LIVE_PRICE_CACHE.get(url)
    if c and (time.time() - c["ts"] < _TTL_PRICE):
        return c["price"]
    soup = _get_soup(url)
    if not soup:
        _LIVE_PRICE_CACHE[url] = {"price": None, "ts": time.time()}
        return None
    # JSON-LD first
    parsed = _parse_jsonld_price_and_image(soup)
    if parsed.get("price"):
        _LIVE_PRICE_CACHE[url] = {"price": parsed["price"], "ts": time.time()}
        return parsed["price"]
    # meta itemprop/OG fallback
    meta = soup.find("meta", attrs={"itemprop": "price"}) or soup.find("meta", attrs={"property": "product:price:amount"})
    if meta and meta.get("content"):
        try:
            price = int(float(meta["content"]))
            _LIVE_PRICE_CACHE[url] = {"price": price, "ts": time.time()}
            return price
        except Exception:
            pass
    # full text fallback
    text = soup.get_text(separator=" ", strip=True)
    price = _parse_price_from_text(text)
    _LIVE_PRICE_CACHE[url] = {"price": price, "ts": time.time()}
    return price

def _fetch_live_image(url: str) -> Optional[str]:
    # cache
    c = _LIVE_IMAGE_CACHE.get(url)
    if c and (time.time() - c["ts"] < _TTL_IMAGE):
        return c["image"]
    soup = _get_soup(url)
    if not soup:
        _LIVE_IMAGE_CACHE[url] = {"image": None, "ts": time.time()}
        return None
    # JSON-LD first
    parsed = _parse_jsonld_price_and_image(soup)
    if parsed.get("image"):
        _LIVE_IMAGE_CACHE[url] = {"image": parsed["image"], "ts": time.time()}
        return parsed["image"]
    # OG/Twitter fallback
    og = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
    if og and og.get("content"):
        img = og["content"].strip()
        _LIVE_IMAGE_CACHE[url] = {"image": img, "ts": time.time()}
        return img
    tw = soup.find("meta", property="twitter:image") or soup.find("meta", attrs={"name": "twitter:image"})
    if tw and tw.get("content"):
        img = tw["content"].strip()
        _LIVE_IMAGE_CACHE[url] = {"image": img, "ts": time.time()}
        return img
    _LIVE_IMAGE_CACHE[url] = {"image": None, "ts": time.time()}
    return None

# -----------------------------
#        CARD HELPERS
# -----------------------------
def _noise_value(p: Dict[str, Any]) -> Optional[float]:
    snd = p.get("sound") or {}
    return snd.get("lwa_measured_db", snd.get("lwa_guaranteed_db"))

def _perimeter_label(perimeter_type: str) -> str:
    mapping = {"virtual": "Virtuale", "wire": "Filo", "both": "Virtuale/Filo"}
    return mapping.get(perimeter_type, perimeter_type)

def build_card(p: Dict[str, Any], score: float) -> Card:
    cov = p.get("coverage_m2", "—")
    slope = p.get("max_slope_pct", "—")
    noise = _noise_value(p)
    perim = _perimeter_label(p.get("perimeter_type", "—"))
    price_val = p.get("price_eur")

    # prezzo formattato
    price_str = "—" if price_val is None else f"{int(price_val):,} €".replace(",", ".")

    specs = [
        SpecItem(label_it="Copertura", label_en="Coverage", value=f"{cov} m²"),
        SpecItem(label_it="Pendenza max", label_en="Max slope", value=f"{slope}%"),
        SpecItem(label_it="Perimetro", label_en="Perimeter", value=perim),
    ]

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

    title_clean = p.get("name", "")
    subtitle = f"{cov} m² • {slope}% • {perim}"

    return Card(
        title=title_clean,
        subtitle=subtitle,
        image_url=p.get("image_url"),
        price=price_obj,
        specs=specs,
        pros=pros,
        cons=[],
        score=round(score, 1),
        links=links
    )

# -----------------------------
#         ENDPOINTS
# -----------------------------
@app.get("/health")
def health():
    return {"status": "ok", "env": os.getenv("ENV", "unknown"), "products_loaded": len(PRODUCTS)}

@app.get("/products/all")
def list_products():
    return {"count": len(PRODUCTS), "items": PRODUCTS}

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
    live_price: bool = True,   # default: ON per coerenza prodotti
    live_image: bool = True    # default: ON per coerenza prodotti
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

    # 2) arricchisci tutti con prezzo/immagine LIVE (skip se PDP non raggiungibile)
    enriched: List[Dict[str, Any]] = []
    for p in filtered:
        p2 = dict(p)
        url = p2.get("pdp_url")
        if not url:
            continue
        soup = _get_soup(url)
        if not soup:
            # se la pagina non è raggiungibile, scarta il prodotto (evita link rotti)
            continue

        # image
        if live_image:
            img = _parse_jsonld_price_and_image(soup).get("image") or \
                  (soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"}))
            if isinstance(img, str):
                p2["image_url"] = img
            elif img and img.get("content"):
                p2["image_url"] = img["content"].strip()
            else:
                # Twitter image fallback
                tw = soup.find("meta", property="twitter:image") or soup.find("meta", attrs={"name": "twitter:image"})
                if tw and tw.get("content"):
                    p2["image_url"] = tw["content"].strip()

        # price
        if live_price:
            lp = _parse_jsonld_price_and_image(soup).get("price")
            if not lp:
                meta = soup.find("meta", attrs={"itemprop": "price"}) or soup.find("meta", attrs={"property": "product:price:amount"})
                if meta and meta.get("content"):
                    try:
                        lp = int(float(meta["content"]))
                    except Exception:
                        lp = None
            if not lp:
                text = soup.get_text(separator=" ", strip=True)
                lp = _parse_price_from_text(text)
            if lp:
                p2["price_eur"] = lp

        enriched.append(p2)

    # 3) scoring + build card
    scored = [(p, score_product(p, q)) for p in enriched]
    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:q.limit]
    cards = [build_card(p, s) for p, s in top]

    meta = {
        "total": len(enriched),
        "limit": q.limit,
        "filters_applied": q.dict()
    }

    return SearchResponse(items=cards, meta=meta)

