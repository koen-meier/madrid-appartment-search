"""
HousingAnywhere scraper — uses their internal search API (JSON).
Mid-term furnished rentals, good coverage for Madrid.
"""
import logging
from typing import Iterator
from .base import Listing, make_client

log = logging.getLogger(__name__)

SEARCH_URL = "https://housinganywhere.com/api/v2/search"

PARAMS = {
    "city": "Madrid, Spain",
    "listingTypes[]": ["apartment", "studio"],
    "priceMax": 1000,
    "currency": "EUR",
    "durationMin": 4,   # min 4 months
    "startDate": "2025-08-01",
    "endDate": "2025-12-31",
    "furnished": "true",
    "page": 1,
    "perPage": 100,
}


def scrape() -> list[Listing]:
    listings = []
    with make_client() as client:
        page = 1
        while True:
            params = {**PARAMS, "page": page}
            try:
                resp = client.get(SEARCH_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                log.error("HousingAnywhere request failed (page %d): %s", page, exc)
                break

            items = data.get("listings") or data.get("data") or data.get("results") or []
            if not items:
                break

            for item in items:
                listing = _parse(item)
                if listing:
                    listings.append(listing)

            total = data.get("total") or data.get("totalCount") or 0
            if page * PARAMS["perPage"] >= total:
                break
            page += 1

    log.info("HousingAnywhere: %d listings", len(listings))
    return listings


def _parse(item: dict) -> Listing | None:
    try:
        price = int(item.get("price") or item.get("monthlyPrice") or 0)
        if price <= 0 or price > 1000:
            return None

        uid = str(item.get("id") or item.get("slug") or "")
        slug = item.get("slug") or uid
        url = f"https://housinganywhere.com/listing/{slug}" if slug else ""

        neighborhood = (
            item.get("neighborhood")
            or item.get("area")
            or item.get("district")
            or item.get("city", "Madrid")
        )

        images = []
        for img in item.get("images") or item.get("photos") or []:
            if isinstance(img, str):
                images.append(img)
            elif isinstance(img, dict):
                images.append(img.get("url") or img.get("src") or "")

        return Listing(
            source="housinganywhere",
            external_id=uid,
            url=url,
            title=item.get("title") or item.get("name") or f"Apartment in {neighborhood}",
            price_eur=price,
            neighborhood=neighborhood,
            area_m2=item.get("area") if isinstance(item.get("area"), int) else None,
            furnished=True,
            available_from=None,
            description=item.get("description") or "",
            images=[i for i in images if i],
            lat=item.get("lat") or item.get("latitude"),
            lng=item.get("lng") or item.get("longitude"),
            raw_data=item,
        )
    except Exception as exc:
        log.warning("HousingAnywhere parse error: %s | item: %s", exc, item)
        return None
