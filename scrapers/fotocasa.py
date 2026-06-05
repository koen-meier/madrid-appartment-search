"""
Fotocasa — Apify actor scraper (bypasses bot detection).
Falls back to httpx HTML scraping if no APIFY_TOKEN.
"""
import json
import logging
import os
import re
import time
import httpx
from bs4 import BeautifulSoup
from .base import Listing

log = logging.getLogger(__name__)

SEARCH_URL = (
    "https://www.fotocasa.es/es/alquiler/viviendas/madrid-capital/todas-las-zonas/l"
    "?maxPrice=1000&furnished=1"
)
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}


def scrape() -> list[Listing]:
    # Try Apify first
    if APIFY_TOKEN:
        listings = _try_apify()
        if listings:
            return listings
        log.info("Fotocasa: Apify returned 0, trying httpx")

    # Fallback: direct httpx
    return _try_httpx()


def _try_apify() -> list[Listing]:
    """Try apify.com/epctex/fotocasa-scraper or similar."""
    base = "https://api.apify.com/v2"
    headers = {"Authorization": f"Bearer {APIFY_TOKEN}", "Content-Type": "application/json"}

    actors_configs = [
        ("epctex/fotocasa-scraper", {
            "startUrls": [{"url": SEARCH_URL}],
            "maxItems": 50,
            "proxyConfiguration": {"useApifyProxy": True},
        }),
        ("epctex/web-scraper", {
            "startUrls": [{"url": SEARCH_URL}],
            "pageFunction": """
async function pageFunction({ $, request }) {
    const items = [];
    $('[class*="re-Card"], [class*="CardPackMinimal"], article').each((i, el) => {
        const link = $(el).find('a[href]').first();
        const price = $(el).find('[class*="re-CardPrice"], [class*="price"]').first();
        const title = $(el).find('h2, h3, [class*="title"]').first();
        const loc = $(el).find('[class*="location"]').first();
        items.push({
            url: link.attr('href') || '',
            priceText: price.text().trim(),
            title: title.text().trim(),
            neighborhood: loc.text().trim() || 'Madrid',
        });
    });
    return items;
}
""",
            "maxRequestsPerCrawl": 3,
        }),
    ]

    for actor_id, payload in actors_configs:
        try:
            with httpx.Client(timeout=90) as client:
                actor_slug = actor_id.replace("/", "~")
                r = client.post(
                    f"{base}/acts/{actor_slug}/runs",
                    headers=headers,
                    json=payload,
                    params={"waitForFinish": 120},
                )
                log.info("Fotocasa Apify %s: start status=%d", actor_id, r.status_code)
                if r.status_code not in (200, 201):
                    log.info("Fotocasa Apify %s: %s", actor_id, r.text[:200])
                    continue

                run_data = r.json()
                run_id = run_data.get("data", {}).get("id") or run_data.get("id")
                if not run_id:
                    continue

                for _ in range(20):
                    sr = client.get(f"{base}/actor-runs/{run_id}", headers=headers)
                    status = sr.json().get("data", {}).get("status", "")
                    if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                        break
                    time.sleep(10)

                if status != "SUCCEEDED":
                    log.warning("Fotocasa Apify %s: %s", actor_id, status)
                    continue

                dataset_id = sr.json().get("data", {}).get("defaultDatasetId", "")
                items_r = client.get(
                    f"{base}/datasets/{dataset_id}/items",
                    headers=headers,
                    params={"format": "json", "limit": 200},
                )
                items = items_r.json()
                log.info("Fotocasa Apify %s: %d items", actor_id, len(items))

                listings = []
                for item in items:
                    l = _parse_apify_item(item)
                    if l:
                        listings.append(l)
                if listings:
                    return listings

        except Exception as exc:
            log.error("Fotocasa Apify %s error: %s", actor_id, exc)

    return []


def _try_httpx() -> list[Listing]:
    """Direct httpx fetch — likely blocked but worth trying."""
    try:
        with httpx.Client(headers=_HEADERS, timeout=30, follow_redirects=True) as client:
            resp = client.get(SEARCH_URL)
            log.info("Fotocasa httpx: status=%d len=%d", resp.status_code, len(resp.text))
            log.info("Fotocasa httpx body: %s", resp.text[:200])
            if resp.status_code != 200:
                return []

            html = resp.text
            # Try __INITIAL_PROPS__ or embedded JSON
            for pat in [r'window\.__INITIAL_PROPS__\s*=\s*(\{.*?\});\s*(?:window|</)',
                        r'"realEstates"\s*:\s*(\[.*?\])',
                        r'window\.__SERVER_PROPS__\s*=\s*(\{.*?\})']:
                m = re.search(pat, html, re.DOTALL)
                if m:
                    try:
                        data = json.loads(m.group(1))
                        items = (
                            data.get("realEstates")
                            or data.get("listings")
                            or (data if isinstance(data, list) else [])
                        )
                        listings = [l for item in items if (l := _parse_fotocasa_item(item))]
                        if listings:
                            log.info("Fotocasa httpx: %d listings from embedded JSON", len(listings))
                            return [l for l in listings if l.price_eur and l.price_eur <= 1000]
                    except Exception:
                        pass

            # DOM parse
            soup = BeautifulSoup(html, "lxml")
            cards = soup.find_all(class_=re.compile(r"re-Card|CardPackMinimal"))
            log.info("Fotocasa httpx DOM cards: %d", len(cards))
            listings = []
            for card in cards[:80]:
                link = card.find("a", href=True)
                price_el = card.find(class_=re.compile(r"re-CardPrice|price"))
                title_el = card.find(["h2", "h3"])
                if not link or not price_el:
                    continue
                url = link["href"]
                if not url.startswith("http"):
                    url = "https://www.fotocasa.es" + url
                nums = re.findall(r"\d+", price_el.get_text().replace(".", ""))
                if not nums:
                    continue
                price = int(nums[0])
                if price <= 0 or price > 1100:
                    continue
                uid = url.rstrip("/").split("/")[-1].split("?")[0]
                listings.append(Listing(
                    source="fotocasa", external_id=uid, url=url,
                    title=(title_el.get_text().strip() if title_el else f"Apartment {uid}"),
                    price_eur=price, neighborhood="Madrid", furnished=True,
                    raw_data={"url": url, "price": price},
                ))
            return listings

    except Exception as exc:
        log.error("Fotocasa httpx error: %s", exc)
    return []


def _parse_apify_item(item: dict) -> "Listing | None":
    try:
        price_info = item.get("priceInfo") or item.get("price") or {}
        price = (
            int(price_info.get("price") or price_info.get("amount") or 0)
            if isinstance(price_info, dict)
            else int(price_info or 0)
        )
        if price <= 0:
            # Try priceText
            price_text = item.get("priceText", "")
            nums = re.findall(r"\d+", price_text.replace(".", ""))
            price = int(nums[0]) if nums else 0
        if price <= 0 or price > 1100:
            return None

        uid = str(item.get("id") or item.get("propertyCode") or "")
        url = item.get("url") or item.get("detail", {}).get("es") or ""
        if url and not url.startswith("http"):
            url = "https://www.fotocasa.es" + url
        if not uid:
            uid = url.rstrip("/").split("/")[-1].split("?")[0]

        location = item.get("ubication") or item.get("location") or {}
        neighborhood = (
            location.get("neighbourhood") or location.get("district")
            or item.get("neighborhood") or "Madrid"
        )

        images = []
        for img in item.get("multimedias") or item.get("images") or []:
            src = (img.get("url") or img.get("src") or "") if isinstance(img, dict) else str(img)
            if src:
                images.append(src)

        return Listing(
            source="fotocasa", external_id=uid, url=url,
            title=item.get("title") or f"Apartment in {neighborhood}",
            price_eur=price, neighborhood=neighborhood, furnished=True,
            images=images[:10], raw_data=item,
        )
    except Exception as exc:
        log.debug("Fotocasa parse error: %s", exc)
        return None


def _parse_fotocasa_item(item: dict) -> "Listing | None":
    return _parse_apify_item(item)
