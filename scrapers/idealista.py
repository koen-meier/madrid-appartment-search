"""
Idealista — Playwright + network interception.
Intercepts the JSON API responses the page makes internally.
"""
import logging
import re
from .base import Listing

log = logging.getLogger(__name__)

SEARCH_URLS = [
    "https://www.idealista.com/alquiler-viviendas/madrid-madrid/con-precio-hasta_1000,amueblado/",
]


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
                if any(k in url for k in ("search", "listings", "inmuebles", "properties", "api")):
                    data = resp.json()
                    captured.append((url, data))
        except Exception:
            pass

    listings = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ))
        page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page.on("response", on_response)
        try:
            page.goto(SEARCH_URLS[0], wait_until="networkidle", timeout=30000)

            # Accept cookies
            for sel in ["#didomi-notice-agree-button", "button:has-text('Aceptar')",
                        "button:has-text('Accept')", "[id*='accept']"]:
                try:
                    page.click(sel, timeout=2000); page.wait_for_timeout(2000); break
                except Exception: pass

            page.wait_for_timeout(2000)

            # Log page title and body excerpt to diagnose bot detection
            title = page.title()
            body_text = page.evaluate("() => document.body.innerText.slice(0, 300)")
            log.info("Idealista page title: %s", title)
            log.info("Idealista body start: %s", body_text)

            # Parse listing cards from the DOM
            items_json = page.evaluate("""
                () => {
                    const cards = document.querySelectorAll('article.item, [class*="item-info"], .items-container article');
                    return Array.from(cards).slice(0, 60).map(card => {
                        const link = card.querySelector('a.item-link, a[href*="/inmueble/"]');
                        const price = card.querySelector('.price-row, [class*="price"]');
                        const title = card.querySelector('.item-title, h2, h3');
                        const loc = card.querySelector('.item-detail-char, [class*="location"]');
                        const img = card.querySelector('img');
                        const detail = card.querySelector('.item-detail');
                        return {
                            url: link ? (link.href || link.getAttribute('href')) : '',
                            priceText: price ? price.innerText : '',
                            title: title ? title.innerText : '',
                            neighborhood: loc ? loc.innerText : 'Madrid',
                            detail: detail ? detail.innerText : '',
                            img: img ? (img.src || img.getAttribute('data-src') || '') : '',
                        };
                    }).filter(x => x.url && x.priceText);
                }
            """)

            log.info("Idealista DOM cards: %d", len(items_json or []))
            for item in (items_json or []):
                l = _parse_dom_item(item)
                if l: listings.append(l)

            # Also check intercepted JSON
            for url, data in captured:
                items = _extract_items(data)
                for item in items:
                    l = _parse_item(item)
                    if l: listings.append(l)

        except Exception as exc:
            log.error("Idealista scrape error: %s", exc)
        finally:
            browser.close()

    seen, unique = set(), []
    for l in listings:
        if l.external_id not in seen:
            seen.add(l.external_id); unique.append(l)

    filtered = [l for l in unique if l.price_eur and l.price_eur <= 1000]
    log.info("Idealista: %d listings", len(filtered))
    return filtered


def _extract_items(data, depth=0) -> list:
    if depth > 5: return []
    if isinstance(data, list) and data and isinstance(data[0], dict):
        if any(k in data[0] for k in ("price", "priceInfo", "propertyCode", "id")):
            return data
    if isinstance(data, dict):
        for v in data.values():
            r = _extract_items(v, depth + 1)
            if r: return r
    return []


def _parse_dom_item(item: dict) -> "Listing | None":
    try:
        url = item.get("url", "")
        if url and not url.startswith("http"):
            url = "https://www.idealista.com" + url
        uid = re.search(r"/inmueble/(\d+)/", url)
        uid = uid.group(1) if uid else url.split("/")[-2]

        price_text = item.get("priceText", "").replace(".", "").replace(",", "").replace("\xa0", "")
        nums = re.findall(r"\d+", price_text)
        if not nums: return None
        price = int(nums[0])
        if price <= 0 or price > 1100: return None

        return Listing(source="idealista", external_id=uid, url=url,
                       title=item.get("title") or f"Apartment {uid}",
                       price_eur=price,
                       neighborhood=item.get("neighborhood") or "Madrid",
                       furnished=True,
                       images=[item["img"]] if item.get("img") else [],
                       raw_data=item)
    except Exception as exc:
        log.debug("Idealista DOM parse error: %s", exc); return None


def _parse_item(item: dict) -> "Listing | None":
    try:
        price = item.get("price") or item.get("priceInfo", {}).get("price") or 0
        price = int(str(price).replace(".", "").split()[0])
        if price <= 0 or price > 1100: return None

        uid = str(item.get("propertyCode") or item.get("id") or "")
        url = item.get("url") or item.get("detailUrl") or ""
        if url and not url.startswith("http"):
            url = "https://www.idealista.com" + url

        neighborhood = item.get("neighborhood") or item.get("district") or "Madrid"
        images = []
        for img in item.get("images") or item.get("photos") or []:
            src = (img.get("url") or img.get("src") or "") if isinstance(img, dict) else img
            if src: images.append(src)

        return Listing(source="idealista", external_id=uid, url=url,
                       title=item.get("suggestedTexts", {}).get("title") or item.get("title") or f"Apt in {neighborhood}",
                       price_eur=price, neighborhood=neighborhood,
                       area_m2=item.get("size") or item.get("area"),
                       furnished=True, description=item.get("description") or "",
                       images=images[:10], lat=item.get("latitude"), lng=item.get("longitude"),
                       raw_data=item)
    except Exception as exc:
        log.debug("Idealista parse error: %s", exc); return None
