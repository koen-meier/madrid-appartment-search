"""
HousingAnywhere — intercepts internal API JSON responses made during page load.
"""
import json
import logging
import re
import httpx
from .base import Listing

log = logging.getLogger(__name__)
SEARCH_URL = "https://housinganywhere.com/s/Madrid--Spain/furnished-apartments"


def scrape() -> list[Listing]:
    listings = _try_api_direct()
    if listings:
        return listings
    return _try_playwright()


def _try_api_direct() -> list[Listing]:
    """Try known HousingAnywhere API endpoints directly with httpx."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://housinganywhere.com/",
    }
    endpoints = [
        "https://housinganywhere.com/api/v2/rooms?cityCanonical=Madrid--Spain&maxPrice=1000&furnishing=true&limit=50",
        "https://housinganywhere.com/api/v2/listings?cityCanonical=Madrid--Spain&maxPrice=1000&furnished=true&limit=50",
        "https://housinganywhere.com/api/search?city=Madrid--Spain&maxPrice=1000&furnished=true",
        "https://housinganywhere.com/api/v3/search?cityCanonical=Madrid--Spain&maxPrice=1000",
    ]
    try:
        with httpx.Client(headers=headers, timeout=20, follow_redirects=True) as client:
            for url in endpoints:
                try:
                    r = client.get(url)
                    log.info("HA API %s: status=%d body=%s", url[:80], r.status_code, r.text[:200])
                    if r.status_code == 200:
                        data = r.json()
                        items = _extract_items(data)
                        if items:
                            log.info("HA API found %d items at %s", len(items), url[:80])
                            return [l for item in items if (l := _parse_item(item))]
                except Exception as e:
                    log.info("HA API %s error: %s", url[:60], e)
    except Exception as exc:
        log.error("HA direct API error: %s", exc)
    return []


def _try_playwright() -> list[Listing]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error("playwright not installed"); return []

    captured = []
    all_urls = []

    def on_request(req):
        try:
            url = req.url
            if "housinganywhere.com" in url and "cdn" not in url and "cookie" not in url.lower():
                all_urls.append(f"{req.method} {url[:120]}")
        except Exception:
            pass

    def on_response(resp):
        try:
            ct = resp.headers.get("content-type", "")
            if resp.status == 200 and "json" in ct:
                url = resp.url
                if "housinganywhere" in url or "imgix" not in url:
                    data = resp.json()
                    captured.append((url, data))
        except Exception:
            pass

    import json as _json

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
        page.on("request", on_request)
        page.on("response", on_response)
        try:
            page.goto(SEARCH_URL, wait_until="networkidle", timeout=30000)
            # Dismiss cookies
            for sel in ["button.cky-btn-accept", "button[aria-label='Accept All']",
                        "#onetrust-accept-btn-handler", "button:has-text('Accept All')"]:
                try:
                    page.click(sel, timeout=2000); page.wait_for_timeout(3000); break
                except Exception: pass
            # Scroll to trigger lazy loading
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(5000)

            # Log ALL housinganywhere.com requests to find the listings API
            log.info("HA all requests: %s", all_urls)

            # Log page content
            log.info("HA page title: %s", page.title())
            log.info("HA body: %s", page.evaluate("() => document.body.innerText.slice(0, 800)"))

            # Extract SSR data
            next_data_str = page.evaluate("""
                () => {
                    const el = document.getElementById('__NEXT_DATA__');
                    return el ? el.textContent : null;
                }
            """)
            if next_data_str:
                try:
                    next_data = _json.loads(next_data_str)
                    page_props = next_data.get("props", {}).get("pageProps", {})
                    log.info("HA __NEXT_DATA__ pageProps keys: %s", list(page_props.keys())[:15])
                    captured.append(("__NEXT_DATA__", next_data))
                except Exception as exc:
                    log.warning("HA __NEXT_DATA__ parse error: %s", exc)
            else:
                # Try window.__INITIAL_STATE__ or similar
                alt = page.evaluate("""
                    () => {
                        for (const k of ['__INITIAL_STATE__', '__APP_STATE__', '__REDUX_STATE__']) {
                            if (window[k]) return JSON.stringify(window[k]);
                        }
                        return null;
                    }
                """)
                if alt:
                    try:
                        alt_data = _json.loads(alt)
                        log.info("HA window state keys: %s", list(alt_data.keys())[:10])
                        captured.append(("__WINDOW_STATE__", alt_data))
                    except Exception as exc:
                        log.warning("HA window state parse error: %s", exc)
                else:
                    log.info("HA: no embedded SSR data found")

        except Exception as exc:
            log.error("HousingAnywhere page error: %s", exc)
        finally:
            browser.close()

    log.info("HousingAnywhere captured %d JSON responses: %s",
             len(captured), [c[0][:80] for c in captured])
    for url, data in captured:
        log.info("HA response from %s: %s", url, _json.dumps(data)[:400])

    listings = []
    for url, data in captured:
        items = _extract_items(data)
        for item in items:
            l = _parse_item(item)
            if l:
                listings.append(l)

    seen, unique = set(), []
    for l in listings:
        if l.external_id not in seen:
            seen.add(l.external_id); unique.append(l)

    filtered = [l for l in unique if l.price_eur and l.price_eur <= 1000]
    log.info("HousingAnywhere Playwright: %d listings", len(filtered))
    return filtered


def _extract_items(data, depth=0) -> list:
    if depth > 6: return []
    if isinstance(data, list) and data and isinstance(data[0], dict):
        if any(k in data[0] for k in ("price", "monthlyPrice", "rent", "id", "homeId", "unitTypeId")):
            return data
    if isinstance(data, dict):
        for v in data.values():
            r = _extract_items(v, depth + 1)
            if r: return r
    return []


def _parse_item(item: dict) -> "Listing | None":
    try:
        price_info = item.get("price") or item.get("monthlyPrice") or item.get("rent") or {}
        price = int(price_info.get("amount") or price_info.get("value") or 0) if isinstance(price_info, dict) else int(price_info or 0)
        if price <= 0 or price > 1100: return None

        uid = str(item.get("id") or item.get("unitTypeId") or item.get("slug") or "")
        slug = item.get("slug") or uid
        url = f"https://housinganywhere.com/listing/{slug}" if slug else ""
        neighborhood = item.get("neighborhood") or item.get("area") or item.get("district") or item.get("city", "Madrid")

        images = []
        for img in item.get("images") or item.get("photos") or []:
            src = (img.get("url") or img.get("src") or "") if isinstance(img, dict) else img
            if src: images.append(src)

        return Listing(source="housinganywhere", external_id=uid, url=url,
                       title=item.get("title") or item.get("name") or f"Apartment in {neighborhood}",
                       price_eur=price, neighborhood=neighborhood,
                       area_m2=item.get("area") if isinstance(item.get("area"), int) else None,
                       furnished=True, description=item.get("description") or "",
                       images=images[:10], lat=item.get("lat") or item.get("latitude"),
                       lng=item.get("lng") or item.get("longitude"), raw_data=item)
    except Exception as exc:
        log.debug("HousingAnywhere parse error: %s", exc); return None
