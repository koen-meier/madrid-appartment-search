"""
Idealista — httpx HTML scraping (primary) with Playwright Firefox fallback.
"""
import json
import logging
import re
import httpx
from bs4 import BeautifulSoup
from .base import Listing

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.idealista.com/alquiler-viviendas/madrid-madrid/con-precio-hasta_1000,amueblado/"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
}


def scrape() -> list[Listing]:
    listings = _try_httpx()
    if not listings:
        log.info("Idealista: httpx returned nothing, trying Playwright Firefox")
        listings = _try_playwright()
    filtered = [l for l in listings if l.price_eur and l.price_eur <= 1000]
    log.info("Idealista: %d listings", len(filtered))
    return filtered


def _try_httpx() -> list[Listing]:
    listings = []
    try:
        with httpx.Client(headers=_HEADERS, timeout=30, follow_redirects=True) as client:
            resp = client.get(SEARCH_URL)
            log.info("Idealista httpx: status=%d url=%s len=%d",
                     resp.status_code, str(resp.url)[:80], len(resp.text))
            log.info("Idealista httpx body start: %s", resp.text[:400])

            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "lxml")

            # Try JSON-LD structured data
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string or "")
                    log.info("Idealista JSON-LD: %s", str(data)[:200])
                    items = _extract_items(data)
                    for item in items:
                        l = _parse_item(item)
                        if l: listings.append(l)
                except Exception:
                    pass

            # Try embedded window.* JSON state
            for script in soup.find_all("script"):
                text = script.string or ""
                for pat in [
                    r'window\.__INITIAL_DATA__\s*=\s*({.+?});?\s*(?:window|</)',
                    r'window\.searchData\s*=\s*({.+?});?\s*(?:window|</)',
                    r'"items"\s*:\s*(\[.+?\])',
                    r'"elementList"\s*:\s*(\[.+?\])',
                ]:
                    m = re.search(pat, text, re.DOTALL)
                    if m:
                        try:
                            data = json.loads(m.group(1))
                            log.info("Idealista script data (pattern %s): %s", pat[:30], str(data)[:300])
                            items = _extract_items(data) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                            for item in items:
                                l = _parse_item(item)
                                if l: listings.append(l)
                        except Exception:
                            pass

            # DOM parse listing articles
            articles = soup.select("article.item, [class*='item-info']")
            log.info("Idealista DOM articles: %d", len(articles))
            for art in articles[:60]:
                link = art.select_one("a.item-link, a[href*='/inmueble/']")
                price_el = art.select_one(".price-row, [class*='price']")
                title_el = art.select_one(".item-title, h2, h3")
                if not link or not price_el:
                    continue
                url = link.get("href", "")
                if url and not url.startswith("http"):
                    url = "https://www.idealista.com" + url
                uid_m = re.search(r"/inmueble/(\d+)/", url)
                uid = uid_m.group(1) if uid_m else url.rstrip("/").split("/")[-1]
                nums = re.findall(r"\d+", price_el.get_text().replace(".", ""))
                if not nums: continue
                price = int(nums[0])
                if price <= 0 or price > 1100: continue
                listings.append(Listing(
                    source="idealista", external_id=uid, url=url,
                    title=(title_el.get_text().strip() if title_el else f"Apartment {uid}"),
                    price_eur=price, neighborhood="Madrid",
                    furnished=True, raw_data={"url": url, "price": price},
                ))

    except Exception as exc:
        log.error("Idealista httpx error: %s", exc)

    seen, unique = set(), []
    for l in listings:
        if l.external_id not in seen:
            seen.add(l.external_id); unique.append(l)
    return unique


def _try_playwright() -> list[Listing]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []

    listings = []
    with sync_playwright() as p:
        browser = p.firefox.launch(headless=True)
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0"
        ))
        page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            page.goto(SEARCH_URL, wait_until="networkidle", timeout=30000)
            for sel in ["#didomi-notice-agree-button", "button:has-text('Aceptar')"]:
                try:
                    page.click(sel, timeout=2000); page.wait_for_timeout(2000); break
                except Exception: pass
            page.wait_for_timeout(2000)
            title = page.title()
            body = page.evaluate("() => document.body.innerText.slice(0, 300)")
            log.info("Idealista Firefox title: %s | body: %s", title, body)

            items_json = page.evaluate("""
                () => {
                    const cards = document.querySelectorAll('article.item, [class*="item-info"]');
                    return Array.from(cards).slice(0, 60).map(card => {
                        const link = card.querySelector('a.item-link, a[href*="/inmueble/"]');
                        const price = card.querySelector('.price-row, [class*="price"]');
                        const title = card.querySelector('.item-title, h2, h3');
                        return {
                            url: link ? (link.href || link.getAttribute('href')) : '',
                            priceText: price ? price.innerText : '',
                            title: title ? title.innerText : '',
                        };
                    }).filter(x => x.url && x.priceText);
                }
            """)
            log.info("Idealista Firefox DOM cards: %d", len(items_json or []))
            for item in (items_json or []):
                url = item.get("url", "")
                if url and not url.startswith("http"):
                    url = "https://www.idealista.com" + url
                uid_m = re.search(r"/inmueble/(\d+)/", url)
                uid = uid_m.group(1) if uid_m else url.rstrip("/").split("/")[-1]
                nums = re.findall(r"\d+", item.get("priceText", "").replace(".", ""))
                if not nums: continue
                price = int(nums[0])
                if 0 < price <= 1100:
                    listings.append(Listing(source="idealista", external_id=uid, url=url,
                                            title=item.get("title") or f"Apartment {uid}",
                                            price_eur=price, neighborhood="Madrid",
                                            furnished=True, raw_data=item))
        except Exception as exc:
            log.error("Idealista Playwright error: %s", exc)
        finally:
            browser.close()

    return listings


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
                       title=(item.get("suggestedTexts", {}).get("title") or
                              item.get("title") or f"Apt in {neighborhood}"),
                       price_eur=price, neighborhood=neighborhood,
                       area_m2=item.get("size") or item.get("area"),
                       furnished=True, description=item.get("description") or "",
                       images=images[:10], lat=item.get("latitude"), lng=item.get("longitude"),
                       raw_data=item)
    except Exception as exc:
        log.debug("Idealista parse error: %s", exc); return None
