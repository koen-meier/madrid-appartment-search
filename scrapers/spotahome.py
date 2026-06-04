"""
Spotahome scraper — reads __NEXT_DATA__ JSON embedded in the search page.
Specialises in mid-term furnished rentals (1–12 months).
"""
import json
import logging
import re
from .base import Listing, make_client

log = logging.getLogger(__name__)

SEARCH_URL = (
    "https://www.spotahome.com/en/for-rent/madrid"
    "?propertyTypes[]=apartment&propertyTypes[]=studio"
    "&maxPrice=1000"
    "&minMonths=4"
    "&maxMonths=6"
    "&amenities[]=furnished"
)


def scrape() -> list[Listing]:
    listings = []
    with make_client() as client:
        try:
            resp = client.get(SEARCH_URL)
            resp.raise_for_status()
            html = resp.text
        except Exception as exc:
            log.error("Spotahome request failed: %s", exc)
            return []

    # Extract __NEXT_DATA__ JSON
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not match:
        log.warning("Spotahome: __NEXT_DATA__ not found — site may have changed")
        return []

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        log.error("Spotahome JSON parse error: %s", exc)
        return []

    # Navigate into the nested structure (structure may vary)
    props = data.get("props", {}).get("pageProps", {})
    items = (
        props.get("properties")
        or props.get("listings")
        or props.get("homes")
        or _deep_find_listings(props)
        or []
    )

    for item in items:
        listing = _parse(item)
        if listing:
            listings.append(listing)

    log.info("Spotahome: %d listings", len(listings))
    return listings


def _deep_find_listings(obj, depth=0) -> list:
    """Recursively look for a list of dicts that look like property listings."""
    if depth > 5:
        return []
    if isinstance(obj, list) and obj and isinstance(obj[0], dict) and "price" in obj[0]:
        return obj
    if isinstance(obj, dict):
        for v in obj.values():
            result = _deep_find_listings(v, depth + 1)
            if result:
                return result
    return []


def _parse(item: dict) -> Listing | None:
    try:
        price_info = item.get("price") or item.get("pricing") or {}
        if isinstance(price_info, dict):
            price = int(price_info.get("amount") or price_info.get("value") or 0)
        else:
            price = int(price_info)
        if price <= 0 or price > 1000:
            return None

        uid = str(item.get("id") or item.get("homeId") or "")
        slug = item.get("slug") or uid
        url = f"https://www.spotahome.com/en/flat-and-house-for-rent/{slug}" if slug else ""

        neighborhood = (
            item.get("neighborhood")
            or item.get("area")
            or item.get("zone")
            or item.get("location", {}).get("neighborhood")
            or "Madrid"
        )

        images = []
        for img in item.get("images") or item.get("photos") or item.get("media") or []:
            if isinstance(img, str):
                images.append(img)
            elif isinstance(img, dict):
                images.append(
                    img.get("url") or img.get("src") or img.get("originalUrl") or ""
                )

        return Listing(
            source="spotahome",
            external_id=uid,
            url=url,
            title=item.get("title") or item.get("name") or f"Apartment in {neighborhood}",
            price_eur=price,
            neighborhood=neighborhood,
            area_m2=item.get("squareMeters") or item.get("area") or item.get("size"),
            furnished=True,
            description=item.get("description") or "",
            images=[i for i in images if i],
            lat=(item.get("location") or {}).get("lat") or item.get("lat"),
            lng=(item.get("location") or {}).get("lng") or item.get("lng"),
            raw_data=item,
        )
    except Exception as exc:
        log.warning("Spotahome parse error: %s | item: %s", exc, item)
        return None
