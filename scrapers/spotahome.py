"""
Spotahome — intercepts internal JSON API calls during page load.
"""
import logging
from .base import Listing

log = logging.getLogger(__name__)
SEARCH_URL = "https://www.spotahome.com/s/madrid/for-rent:apartments"


def scrape() -> list[Listing]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error("playwright not installed"); return []

    captured = []

    def on_response(resp):
        try:
            ct = resp.headers.get("content-type", "")
            if resp.status == 200 and "json" in ct:
                url = resp.url
                if any(k in url for k in ("search", "listings", "homes", "properties", "units", "rental", "graphql")):
                    data = resp.json()
                    captured.append((url, data))
        except Exception:
            pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ))
        page.on("response", on_response)
        try:
            page.goto(SEARCH_URL, wait_until="networkidle", timeout=30000)
            for sel in ["button.cky-btn-accept", "button[data-cky-tag='accept-button']",
                        "button[aria-label='Accept All']", "button:has-text('Accept All')"]:
                try:
                    page.click(sel, timeout=2000); page.wait_for_timeout(3000); break
                except Exception: pass
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(3000)
        except Exception as exc:
            log.error("Spotahome page error: %s", exc)
        finally:
            browser.close()

    log.info("Spotahome captured %d JSON responses: %s",
             len(captured), [c[0][:80] for c in captured])
    for url, data in captured:
        import json as _json
        log.info("Spotahome response from %s: %s", url, _json.dumps(data)[:500])

    listings = []
    for url, data in captured:
        items = _extract_items(data)
        for item in items:
            l = _parse_item(item)
            if l: listings.append(l)

    seen, unique = set(), []
    for l in listings:
        if l.external_id not in seen:
            seen.add(l.external_id); unique.append(l)

    filtered = [l for l in unique if l.price_eur and l.price_eur <= 1000]
    log.info("Spotahome: %d listings", len(filtered))
    return filtered


def _extract_items(data, depth=0) -> list:
    if depth > 6: return []
    if isinstance(data, list) and len(data) > 1 and isinstance(data[0], dict):
        if any(k in data[0] for k in ("price", "priceInfo", "id", "homeId", "slug")):
            return data
    if isinstance(data, dict):
        for v in data.values():
            r = _extract_items(v, depth + 1)
            if r: return r
    return []


def _parse_item(item: dict) -> "Listing | None":
    try:
        price_info = item.get("price") or item.get("priceInfo") or item.get("pricing") or {}
        price = int(price_info.get("amount") or price_info.get("value") or price_info.get("price") or 0) if isinstance(price_info, dict) else int(price_info or 0)
        if price <= 0 or price > 1100: return None

        uid = str(item.get("id") or item.get("homeId") or item.get("slug") or "")
        slug = item.get("slug") or uid
        url = f"https://www.spotahome.com/en/flat-and-house-for-rent/{slug}" if slug else ""
        location = item.get("location") or {}
        neighborhood = (item.get("neighborhood") or item.get("area") or item.get("zone")
                        or (location.get("neighborhood") if isinstance(location, dict) else None) or "Madrid")

        images = []
        for img in item.get("images") or item.get("photos") or item.get("media") or []:
            src = (img.get("url") or img.get("src") or "") if isinstance(img, dict) else img
            if src: images.append(src)

        return Listing(source="spotahome", external_id=uid, url=url,
                       title=item.get("title") or item.get("name") or f"Apartment in {neighborhood}",
                       price_eur=price, neighborhood=neighborhood,
                       area_m2=item.get("squareMeters") or item.get("area") or item.get("size"),
                       furnished=True, description=item.get("description") or "",
                       images=images[:10],
                       lat=(location.get("lat") if isinstance(location, dict) else None) or item.get("lat"),
                       lng=(location.get("lng") if isinstance(location, dict) else None) or item.get("lng"),
                       raw_data=item)
    except Exception as exc:
        log.debug("Spotahome parse error: %s", exc); return None
