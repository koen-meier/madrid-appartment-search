"""
Fotocasa scraper — reads JSON-LD + embedded page data from search results.
Major Spanish real estate portal.
"""
import json
import logging
import re
from .base import Listing, make_client

log = logging.getLogger(__name__)

# Alquiler temporal (mid-term) furnished apartments in Madrid under €1000
SEARCH_URL = (
    "https://www.fotocasa.es/es/alquiler/viviendas/madrid-capital/todas-las-zonas/l"
    "?maxPrice=1000"
    "&furnished=1"
)

SEARCH_API_URL = (
    "https://api.fotocasa.es/v2/propertysearch/search"
    "?operation=rent&propertyType=homes&locationIds=724,14,28,28079,0,1,300"
    "&maxPrice=1000&furnished=1&pageSize=100&page={page}&culture=en-ES"
)


def scrape() -> list[Listing]:
    listings = []
    with make_client() as client:
        page = 1
        while True:
            url = SEARCH_API_URL.format(page=page)
            try:
                resp = client.get(url)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                # Fall back to HTML scraping
                data = _scrape_html(client)
                listings.extend([l for item in (data or []) if (l := _parse(item))])
                break

            items = (
                data.get("realEstates")
                or data.get("listings")
                or data.get("items")
                or []
            )
            if not items:
                break

            for item in items:
                listing = _parse(item)
                if listing:
                    listings.append(listing)

            total = data.get("totalResults") or data.get("total") or 0
            if page * 100 >= total:
                break
            page += 1

    log.info("Fotocasa: %d listings", len(listings))
    return listings


def _scrape_html(client) -> list[dict]:
    """Fallback: extract embedded JSON from HTML page."""
    try:
        resp = client.get(SEARCH_URL)
        resp.raise_for_status()
        html = resp.text
    except Exception as exc:
        log.error("Fotocasa HTML request failed: %s", exc)
        return []

    # Try window.__INITIAL_PROPS__ or similar
    for pattern in [
        r'window\.__INITIAL_PROPS__\s*=\s*({.*?});\s*</script>',
        r'window\.__SERVER_PROPS__\s*=\s*({.*?});\s*</script>',
        r'"realEstates"\s*:\s*(\[.*?\])',
    ]:
        match = re.search(pattern, html, re.DOTALL)
        if match:
            try:
                obj = json.loads(match.group(1))
                if isinstance(obj, list):
                    return obj
                items = obj.get("realEstates") or obj.get("listings") or []
                if items:
                    return items
            except Exception:
                continue

    log.warning("Fotocasa: could not extract listings from HTML")
    return []


def _parse(item: dict) -> Listing | None:
    try:
        price_info = item.get("priceInfo") or item.get("price") or {}
        if isinstance(price_info, dict):
            price = int(price_info.get("price") or price_info.get("amount") or 0)
        else:
            price = int(price_info)
        if price <= 0 or price > 1000:
            return None

        uid = str(item.get("id") or item.get("propertyCode") or "")
        url = item.get("detail", {}).get("es") or item.get("url") or ""
        if url and not url.startswith("http"):
            url = "https://www.fotocasa.es" + url

        location = item.get("ubication") or item.get("location") or {}
        neighborhood = (
            location.get("neighbourhood")
            or location.get("neighborhood")
            or location.get("district")
            or item.get("neighborhood")
            or "Madrid"
        )

        features = item.get("features") or item.get("characteristics") or {}
        area_m2 = features.get("constructedArea") or features.get("area") or item.get("area")

        images = []
        for img in item.get("multimedias") or item.get("images") or item.get("photos") or []:
            if isinstance(img, str):
                images.append(img)
            elif isinstance(img, dict):
                images.append(img.get("url") or img.get("src") or "")

        title = (
            item.get("suggestedTexts", {}).get("title")
            or item.get("title")
            or f"Apartment in {neighborhood}"
        )

        return Listing(
            source="fotocasa",
            external_id=uid,
            url=url,
            title=title,
            price_eur=price,
            neighborhood=neighborhood,
            area_m2=int(area_m2) if area_m2 else None,
            furnished=True,
            description=item.get("description") or "",
            images=[i for i in images if i],
            lat=location.get("lat") or location.get("latitude"),
            lng=location.get("lng") or location.get("longitude"),
            raw_data=item,
        )
    except Exception as exc:
        log.warning("Fotocasa parse error: %s | item: %s", exc, item)
        return None
