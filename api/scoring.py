from typing import Dict, Any
from .models import SearchQuery
from typing import Optional  # aggiungi in alto se non è già presente

def _noise_value(p: Dict[str, Any]) -> Optional[float]:
    snd = p.get("sound") or {}
    return snd.get("lwa_measured_db", snd.get("lwa_guaranteed_db"))

def score_product(p: Dict[str, Any], q: SearchQuery) -> float:
    score = 0.0

    # 0–35 Copertura
    cov = p.get("coverage_m2", 0)
    if cov >= q.surface_m2:
        ratio = q.surface_m2 / cov
        if ratio <= 0.5:
            score += 35
        elif ratio <= 0.75:
            score += 30
        elif ratio <= 0.9:
            score += 24
        else:
            score += 18

    # 0–15 Pendenza
    slope = p.get("max_slope_pct", 0)
    if slope >= q.slope_pct:
        delta = slope - q.slope_pct
        if delta >= 15: score += 15
        elif delta >= 10: score += 12
        elif delta >= 5: score += 9
        else: score += 6

    # 0–15 Budget
    price = p.get("price_eur")
    band = (q.budget_band or "any")
    if band == "any" or price is None:
        score += 7.5
    else:
        if band == "low":
            score += 15 if price <= 800 else (8 if price <= 1200 else 0)
        elif band == "mid":
            score += 15 if 800 <= price <= 1500 else (8 if 600 <= price <= 2200 else 0)
        elif band == "high":
            score += 15 if price >= 1500 else (8 if 1200 <= price < 1500 else 0)

    # 0–15 Rumorosità
    if q.noise_pref is not None:
        nv = _noise_value(p)
        if nv is not None:
            if nv <= q.noise_pref: score += 15
            elif nv <= q.noise_pref + 3: score += 10
            elif nv <= q.noise_pref + 6: score += 5

    # 0–5 Multizona
    if q.multizone:
        zones = (p.get("zones") or {})
        managed = zones.get("managed", 1)
        if managed >= 2:
            score += 5

    # +5 Power source coerente
    if q.power_source and q.power_source != "any" and p.get("power_source") == q.power_source:
        score += 5

    # +10 Feature extra (max 1 punto ciascuna)
    feats_req = set((q.features or []))
    if feats_req:
        feats_have = set(p.get("features") or [])
        add = 0
        for f in feats_req:
            if f == "wireless":
                if p.get("wireless"): add += 1
            elif f in feats_have:
                add += 1
        score += min(add, 10)

    # Bonus +5 wireless se richiesto e disponibile
    if "wireless" in (q.features or []) and p.get("wireless"):
        score += 5

    return max(0.0, min(100.0, score))
