"""
Fotocasa scraper — Playwright to bypass 405/anti-bot, extract __INITIAL_PROPS__ or DOM.
"""
import json
import logging
import re
from .base import Listing

log = logging.getLogger(__name__)

SEARCH_URL = (
    "https://www.fotocasa.es/es/alquiler/viviendas/madrid-capital/todas-las-zonas/l"
    "?maxPrice=1000&furnished=1"
)


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

            # Accept cookie banner
            for selector in ["#didomi-notice-agree-button", "button:has-text('Aceptar todo')",
                              "button:has-text('Aceptar')", "button:has-text('Accept all')",
                              "[data-testid='accept-button']"]:
                try:
                    page.click(selector, timeout=3000)
                    page.wait_for_timeout(2000)
                    break
                except Exception:
                    pass

            # Wait for listing cards
            try:
                page.wait_for_selector("[class*='re-Card'], article[class*='card']", timeout=8000)
            except Exception:
                pass

            # Try to extract embedded JSON
            props = page.evaluate("""
                () => {
                    for (const key of ['__INITIAL_PROPS__', '__SERVER_PROPS__', '__NUXT__']) {
                        if (window[key]) return JSON.stringify(window[key]);
                    }
                    const scripts = document.querySelectorAll('script:not([src])');
                    for (const s of scripts) {
                        if (s.textContent.includes('"realEstates"')) return s.textContent;
                    }
                    return null;
                }
            """)

            if props:
                try:
                    data = json.loads(props)
                    items = (
                        data.get("realEstates")
                        or data.get("listings")
                        or _deep_find(data, "realEstates")
                        or []
                    )
                    listings = [l for item in items if (l := _parse_item(item))]
                    log.info("Fotocasa: %d from page data", len(listings))
                except Exception as exc:
                    log.warning("Fotocasa props parse error: %s", exc)

            if not listings:
                items_json = page.evaluate("""
                    () => {
                        const cards = document.querySelectorAll('[class*="re-CardPackMinimal"], [class*="CardPackPremium"], article');
                        return Array.from(cards).slice(0, 80).map(card => {
                            const link = card.querySelector('a[href]');
                            const price = card.querySelector('[class*="re-CardPrice"], [class*="price"]');
                            const title = card.querySelector('h2, h3, [class*="title"]');
                            const loc = card.querySelector('[class*="CardLocation"], [class*="location"]');
                            const img = card.querySelector('img');
                            return {
                                url: link ? link.href : '',
                                priceText: price ? price.innerText : '',
                                title: title ? title.innerText : '',
                                neighborhood: loc ? loc.innerText : 'Madrid',
                                img: img ? (img.src || img.dataset.src || '') : '',
                            };
                        }).filter(x => x.url && x.priceText);
                    }
                """)
                listings = [l for item in (items_json or []) if (l := _parse_dom_item(item))]
                log.info("Fotocasa: %d from DOM", len(listings))

        except Exception as exc:
            log.error("Fotocasa scrape error: %s", exc)
        finally:
            browser.close()

    filtered = [l for l in listings if l.price_eur and l.price_eur <= 1000]
    log.info("Fotocasa: %d listings after filter", len(filtered))
    return filtered


def _deep_find(obj, key, depth=0):
    if depth > 5:
        return None
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = _deep_find(v, key, depth + 1)
            if r:
                return r
    return None


def _parse_dom_item(item: dict) -> Listing | None:
    try:
        url = item.get("url", "")
        if url and not url.startswith("http"):
            url = "https://www.fotocasa.es" + url
        uid = url.rstrip("/").split("/")[-1].split("?")[0]
        nums = re.findall(r"\d+", item.get("priceText", "").replace(".", "").replace(",", ""))
        if not nums:
            return None
        price = int(nums[0])
        if price <= 0 or price > 1100:
            return None
        return Listing(
            source="fotocasa",
            external_id=uid or url,
            url=url,
            title=item.get("title") or f"Apartment {uid}",
            price_eur=price,
            neighborhood=item.get("neighborhood") or "Madrid",
            furnished=True,
            images=[item["img"]] if item.get("img") else [],
            raw_data=item,
        )
    except Exception as exc:
        log.debug("Fotocasa DOM parse error: %s", exc)
        return None


def _parse_item(item: dict) -> Listing | None:
    try:
        price_info = item.get("priceInfo") or item.get("price") or {}
        price = int(price_info.get("price") or price_info.get("amount") or 0) if isinstance(price_info, dict) else int(price_info or 0)
        if price <= 0 or price > 1100:
            return None

        uid = str(item.get("id") or item.get("propertyCode") or "")
        url = item.get("detail", {}).get("es") or item.get("url") or ""
        if url and not url.startswith("http"):
            url = "https://www.fotocasa.es" + url

        location = item.get("ubication") or item.get("location") or {}
        neighborhood = (
            location.get("neighbourhood") or location.get("district")
            or item.get("neighborhood") or "Madrid"
        )
        features = item.get("features") or item.get("characteristics") or {}
        area_m2 = features.get("constructedArea") or features.get("area") or item.get("area")

        images = []
        for img in item.get("multimedias") or item.get("images") or []:
            src = img.get("url") or img.get("src") or "" if isinstance(img, dict) else img
            if src:
                images.append(src)

        return Listing(
            source="fotocasa",
            external_id=uid,
            url=url,
            title=item.get("suggestedTexts", {}).get("title") or item.get("title") or f"Apartment in {neighborhood}",
            price_eur=price,
            neighborhood=neighborhood,
            area_m2=int(area_m2) if area_m2 else None,
            furnished=True,
            description=item.get("description") or "",
            images=images[:10],
            lat=location.get("lat") or location.get("latitude"),
            lng=location.get("lng") or location.get("longitude"),
            raw_data=item,
        )
    except Exception as exc:
        log.warning("Fotocasa parse error: %s", exc)
        return None
