"""
Spotahome — direct GraphQL via httpx, with Playwright fallback.
"""
import json
import logging
import httpx
from .base import Listing

log = logging.getLogger(__name__)

GRAPHQL_URL = "https://www.spotahome.com/marketplace/graphql"
CITY_PAGE_URL = "https://www.spotahome.com/s/madrid/for-rent:apartments?checkIn=2026-08-01&checkOut=2026-12-31&maxPrice=100000"

_GQL_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Referer": "https://www.spotahome.com/s/madrid/for-rent:apartments",
    "Origin": "https://www.spotahome.com",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def scrape() -> list[Listing]:
    listings = _try_graphql_direct()
    if not listings:
        log.info("Spotahome: direct GraphQL returned nothing, trying Playwright")
        listings = _try_playwright()

    filtered = [l for l in listings if l.price_eur and l.price_eur <= 1000]
    log.info("Spotahome: %d listings", len(filtered))
    return filtered


def _try_graphql_direct() -> list[Listing]:
    listings = []
    try:
        with httpx.Client(headers=_GQL_HEADERS, timeout=30, follow_redirects=True) as client:
            # Discover available query names via introspection
            r = client.post(GRAPHQL_URL, json={
                "query": "{ __schema { queryType { fields { name } } } }"
            })
            if r.status_code == 200:
                fields = (r.json().get("data") or {}).get("__schema", {}).get("queryType", {}).get("fields", [])
                names = [f["name"] for f in fields]
                log.info("Spotahome available GraphQL queries: %s", names)

                # Find likely listing search queries
                search_queries = [n for n in names if any(k in n.lower() for k in
                    ("search", "listing", "home", "apartment", "room", "rental", "property"))]
                log.info("Spotahome candidate listing queries: %s", search_queries)

                # Try each candidate query with minimal field selection to see what works
                for qname in search_queries[:5]:
                    try:
                        r2 = client.post(GRAPHQL_URL, json={
                            "operationName": qname,
                            "variables": {
                                "cityId": "madrid",
                                "city": "madrid",
                                "checkIn": "2026-08-01",
                                "checkOut": "2026-12-31",
                                "maxPrice": 100000,
                                "propertyType": "apartment",
                                "page": 1,
                                "limit": 50,
                            },
                            "query": f"query {qname} {{ {qname} {{ __typename }} }}"
                        })
                        log.info("Spotahome query %s: status=%d body=%s",
                                 qname, r2.status_code, r2.text[:200])
                    except Exception as e:
                        log.info("Spotahome query %s failed: %s", qname, e)
            else:
                log.info("Spotahome introspection: status=%d body=%s", r.status_code, r.text[:300])

    except Exception as exc:
        log.error("Spotahome GraphQL direct error: %s", exc)

    return listings


def _try_playwright() -> list[Listing]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []

    captured = []
    gql_queries = []

    def on_request(req):
        try:
            if "graphql" in req.url and req.method == "POST":
                gql_queries.append((req.post_data or "")[:400])
        except Exception:
            pass

    def on_response(resp):
        try:
            ct = resp.headers.get("content-type", "")
            if resp.status == 200 and "json" in ct and "graphql" in resp.url:
                captured.append((resp.url, resp.json()))
        except Exception:
            pass

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
            page.goto(CITY_PAGE_URL, wait_until="networkidle", timeout=30000)
            for sel in ["button.cky-btn-accept", "button[aria-label='Accept All']",
                        "button:has-text('Accept All')"]:
                try:
                    page.click(sel, timeout=2000); break
                except Exception: pass
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(4000)

            # Log all window state keys to find where listings live
            win_keys = page.evaluate("""
                () => Object.keys(window).filter(k =>
                    k.includes('STATE') || k.includes('DATA') || k.includes('QUERY') ||
                    k.includes('REDUX') || k.includes('STORE') || k.includes('listing') ||
                    k.includes('search') || k.includes('home'))
            """)
            log.info("Spotahome window keys: %s", win_keys)
            log.info("Spotahome GQL queries sent: %s", gql_queries)

        except Exception as exc:
            log.error("Spotahome Playwright error: %s", exc)
        finally:
            browser.close()

    listings = []
    for url, data in captured:
        for item in _extract_items(data):
            l = _parse_item(item)
            if l: listings.append(l)

    seen, unique = set(), []
    for l in listings:
        if l.external_id not in seen:
            seen.add(l.external_id); unique.append(l)
    return unique


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
        price = (
            int(price_info.get("amount") or price_info.get("value") or price_info.get("price") or 0)
            if isinstance(price_info, dict) else int(price_info or 0)
        )
        if price <= 0 or price > 1100: return None

        uid = str(item.get("id") or item.get("homeId") or item.get("slug") or "")
        slug = item.get("slug") or uid
        url = f"https://www.spotahome.com/en/flat-and-house-for-rent/{slug}" if slug else ""
        location = item.get("location") or {}
        neighborhood = (
            item.get("neighborhood") or item.get("area") or item.get("zone")
            or (location.get("neighborhood") if isinstance(location, dict) else None) or "Madrid"
        )
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
