"""
HousingAnywhere scraper — uses Playwright to load the JS-rendered page,
then extracts listing data from __NEXT_DATA__ or the DOM.
"""
import json
import logging
import re
from .base import Listing

log = logging.getLogger(__name__)

SEARCH_URL = "https://housinganywhere.com/s/Madrid--Spain/furnished-apartments"


def scrape() -> list[Listing]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error("playwright not installed")
        return []

    listings = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        try:
            page.goto(SEARCH_URL, wait_until="networkidle", timeout=30000)

            # Extract __NEXT_DATA__
            next_data = page.evaluate("""
                () => {
                    const el = document.getElementById('__NEXT_DATA__');
                    return el ? el.textContent : null;
                }
            """)

            if next_data:
                data = json.loads(next_data)
                items = _deep_find_listings(data)
                if items:
                    listings = [l for item in items if (l := _parse_item(item))]
                    log.info("HousingAnywhere: %d from __NEXT_DATA__", len(listings))

            if not listings:
                # Debug: log page title and a sample of body HTML
                title = page.title()
                sample = page.evaluate("() => document.body.innerHTML.slice(0, 3000)")
                log.info("HousingAnywhere page title: %s", title)
                log.info("HousingAnywhere HTML sample: %s", sample)

                # Fallback: extract from visible DOM
                items_json = page.evaluate("""
                    () => {
                        const cards = document.querySelectorAll('[data-qa="property-card"], [class*="ListingCard"]');
                        return Array.from(cards).map(card => {
                            const link = card.querySelector('a[href]');
                            const price = card.querySelector('[class*="price"], [data-qa*="price"]');
                            const title = card.querySelector('h2, h3, [class*="title"]');
                            const loc = card.querySelector('[class*="location"], [class*="area"]');
                            const img = card.querySelector('img');
                            return {
                                url: link ? link.href : '',
                                priceText: price ? price.innerText : '',
                                title: title ? title.innerText : '',
                                neighborhood: loc ? loc.innerText : 'Madrid',
                                img: img ? (img.src || img.dataset.src || '') : '',
                            };
                        });
                    }
                """)
                listings = [l for item in (items_json or []) if (l := _parse_dom_item(item))]
                log.info("HousingAnywhere: %d from DOM", len(listings))

        except Exception as exc:
            log.error("HousingAnywhere scrape error: %s", exc)
        finally:
            browser.close()

    filtered = [l for l in listings if l.price_eur and l.price_eur <= 1000]
    log.info("HousingAnywhere: %d listings after filter", len(filtered))
    return filtered


def _deep_find_listings(obj, depth=0) -> list:
    if depth > 7:
        return []
    if isinstance(obj, list) and len(obj) > 1 and isinstance(obj[0], dict):
        if any(k in obj[0] for k in ("price", "monthlyPrice", "rent", "id", "homeId")):
            return obj
    if isinstance(obj, dict):
        for v in obj.values():
            r = _deep_find_listings(v, depth + 1)
            if r:
                return r
    return []


def _parse_dom_item(item: dict) -> Listing | None:
    try:
        url = item.get("url", "")
        uid = url.rstrip("/").split("/")[-1].split("?")[0]
        nums = re.findall(r"\d+", item.get("priceText", "").replace(".", "").replace(",", ""))
        if not nums:
            return None
        price = int(nums[0])
        if price <= 0 or price > 1100:
            return None
        images = [item["img"]] if item.get("img") else []
        return Listing(
            source="housinganywhere",
            external_id=uid or url,
            url=url,
            title=item.get("title") or f"Apartment {uid}",
            price_eur=price,
            neighborhood=item.get("neighborhood") or "Madrid",
            furnished=True,
            images=images,
            raw_data=item,
        )
    except Exception as exc:
        log.debug("HousingAnywhere DOM parse error: %s", exc)
        return None


def _parse_item(item: dict) -> Listing | None:
    try:
        price_info = item.get("price") or item.get("monthlyPrice") or item.get("rent") or {}
        price = int(price_info.get("amount") or price_info.get("value") or 0) if isinstance(price_info, dict) else int(price_info or 0)
        if price <= 0 or price > 1100:
            return None

        uid = str(item.get("id") or item.get("slug") or "")
        slug = item.get("slug") or uid
        url = f"https://housinganywhere.com/listing/{slug}" if slug else ""
        neighborhood = item.get("neighborhood") or item.get("area") or item.get("district") or item.get("city", "Madrid")

        images = []
        for img in item.get("images") or item.get("photos") or []:
            src = img.get("url") or img.get("src") or "" if isinstance(img, dict) else img
            if src:
                images.append(src)

        return Listing(
            source="housinganywhere",
            external_id=uid,
            url=url,
            title=item.get("title") or item.get("name") or f"Apartment in {neighborhood}",
            price_eur=price,
            neighborhood=neighborhood,
            area_m2=item.get("area") if isinstance(item.get("area"), int) else None,
            furnished=True,
            description=item.get("description") or "",
            images=images[:10],
            lat=item.get("lat") or item.get("latitude"),
            lng=item.get("lng") or item.get("longitude"),
            raw_data=item,
        )
    except Exception as exc:
        log.warning("HousingAnywhere item parse error: %s", exc)
        return None
