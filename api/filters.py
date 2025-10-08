from typing import Dict, Any, List
from .models import SearchQuery

def _perimeter_ok(perimeter_type: str, requested: str) -> bool:
    if requested == "any":
        return True
    if requested == "virtual":
        return perimeter_type in {"virtual", "both"}
    if requested == "wire":
        return perimeter_type in {"wire", "both"}
    if requested == "both":
        return perimeter_type == "both"
    return True

def hard_filters(products: List[Dict[str, Any]], q: SearchQuery) -> List[Dict[str, Any]]:
    """
    Applica i filtri duri:
      - coverage_m2 >= surface_m2
      - max_slope_pct >= slope_pct
      - perimetro compatibile
      - power_source (se specificato e != any)
    """
    out: List[Dict[str, Any]] = []
    for p in products:
        cov = p.get("coverage_m2", 0)
        slope = p.get("max_slope_pct", 0)
        perimeter_type = p.get("perimeter_type", "both")
        power_source = p.get("power_source", "battery")

        if cov < q.surface_m2:
            continue
        if slope < q.slope_pct:
            continue
        if not _perimeter_ok(perimeter_type, q.perimeter):
            continue
        if q.power_source and q.power_source != "any" and power_source != q.power_source:
            continue

        out.append(p)
    return out
