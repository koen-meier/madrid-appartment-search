"""
HousingAnywhere — httpx + parse window.__staticRouterHydrationData from SSR HTML.
Listings are embedded in the initial HTML payload in loaderData['0-22']['listings'].
"""
import json
import logging
import re
import httpx
from .base import Listing

log = logging.getLogger(__name__)

SEARCH_URL = "https://housinganywhere.com/s/Madrid--Spain/furnished-apartments"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}


def scrape() -> list[Listing]:
    listings = []
    try:
        with httpx.Client(headers=_HEADERS, timeout=30, follow_redirects=True) as client:
            resp = client.get(SEARCH_URL)
            log.info("HousingAnywhere: status=%d len=%d", resp.status_code, len(resp.text))
            if resp.status_code != 200:
                return []

            html = resp.text

            # Extract window.__staticRouterHydrationData = JSON.parse("...")
            m = re.search(
                r'window\.__staticRouterHydrationData\s*=\s*JSON\.parse\("(.*?)"\);\s*</script>',
                html,
                re.DOTALL,
            )
            if not m:
                log.warning("HousingAnywhere: __staticRouterHydrationData not found")
                log.info("HousingAnywhere page start: %s", html[:300])
                return []

            raw = m.group(1)
            # Unescape: the JSON string is double-escaped
            raw = raw.encode("utf-8").decode("unicode_escape")
            data = json.loads(raw)

            loader = data.get("loaderData", {})
            # Listings are in loaderData['0-22']['listings'] (key may vary)
            raw_listings = None
            for key, val in loader.items():
                if isinstance(val, dict) and "listings" in val:
                    raw_listings = val["listings"]
                    log.info("HousingAnywhere: found listings under loaderData[%r]", key)
                    break

            if not raw_listings:
                log.warning("HousingAnywhere: listings not found in loaderData keys=%s", list(loader.keys()))
                return []

            log.info("HousingAnywhere: %d raw listings from SSR", len(raw_listings))
            for item in raw_listings:
                l = _parse_item(item)
                if l:
                    listings.append(l)

    except Exception as exc:
        log.error("HousingAnywhere error: %s", exc)

    seen, unique = set(), []
    for l in listings:
        if l.external_id not in seen:
            seen.add(l.external_id)
            unique.append(l)

    filtered = [l for l in unique if l.price_eur and l.price_eur <= 1000]
    log.info("HousingAnywhere: %d listings (≤€1000)", len(filtered))
    return filtered


def _parse_item(item: dict) -> "Listing | None":
    try:
        # priceEUR is the monthly EUR price; minPrice is the minimum price
        price = item.get("priceEUR") or item.get("minPrice") or 0
        price = int(price)
        if price <= 0 or price > 1100:
            return None

        uid = str(item.get("id") or item.get("unitTypeInternalID") or item.get("objectID") or "")
        if not uid:
            return None

        path = item.get("path") or item.get("unitTypePath") or item.get("listingPath") or ""
        url = f"https://housinganywhere.com{path}" if path else ""

        neighborhood = item.get("neighborhood") or item.get("city") or "Madrid"
        # Fix encoding issues
        try:
            neighborhood = neighborhood.encode("latin-1").decode("utf-8")
        except Exception:
            pass

        geo = item.get("_geoloc") or {}
        lat = geo.get("lat") or item.get("latitude")
        lng = geo.get("lng") or item.get("longitude")

        photos = item.get("photos") or []
        images = []
        for p in photos[:5]:
            src = (p.get("url") or p.get("src") or "") if isinstance(p, dict) else str(p)
            if src:
                images.append(src)
        if not images and item.get("thumbnailURL"):
            images = [item["thumbnailURL"]]

        area_m2 = item.get("facility_total_size") or item.get("facility_bedroom_size")
        if area_m2:
            try:
                area_m2 = int(float(area_m2))
            except Exception:
                area_m2 = None

        return Listing(
            source="housinganywhere",
            external_id=uid,
            url=url,
            title=f"Apartment in {neighborhood}",
            price_eur=price,
            neighborhood=neighborhood,
            area_m2=area_m2,
            furnished=True,
            lat=lat,
            lng=lng,
            images=images,
            raw_data=item,
        )
    except Exception as exc:
        log.debug("HousingAnywhere parse error: %s", exc)
        return None
