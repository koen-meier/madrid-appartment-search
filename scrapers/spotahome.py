"""
Spotahome — httpx HTML scraping of SSR search results pages.
Listings are server-side rendered when dates are provided in the URL.
"""
import logging
import re
import time
import httpx
from bs4 import BeautifulSoup
from .base import Listing

log = logging.getLogger(__name__)

BASE_URL = "https://www.spotahome.com"
SEARCH_URL = (
    "https://www.spotahome.com/s/madrid/for-rent:apartments"
    "?checkIn=2026-08-01&checkOut=2026-12-31"
)
PAGE_URL = (
    "https://www.spotahome.com/s/madrid/for-rent:apartments/page:{page}"
    "?checkIn=2026-08-01&checkOut=2026-12-31"
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    # Do NOT set Accept-Encoding — let httpx handle decompression automatically
}


def scrape() -> list[Listing]:
    listings = []
    try:
        with httpx.Client(headers=_HEADERS, timeout=30, follow_redirects=True) as client:
            for page in range(1, 6):  # up to 5 pages
                url = SEARCH_URL if page == 1 else PAGE_URL.format(page=page)
                resp = client.get(url)
                log.info("Spotahome page %d: status=%d len=%d", page, resp.status_code, len(resp.text))
                if resp.status_code != 200:
                    break
                page_listings = _parse_page(resp.text)
                log.info("Spotahome page %d: %d listings parsed", page, len(page_listings))
                if page == 1 and not page_listings:
                    log.info("Spotahome page 1 body start: %s", resp.text[:400])
                listings.extend(page_listings)
                if not page_listings:
                    break
    except Exception as exc:
        log.error("Spotahome httpx error: %s", exc)

    # Deduplicate
    seen, unique = set(), []
    for l in listings:
        if l.external_id not in seen:
            seen.add(l.external_id)
            unique.append(l)

    filtered = [l for l in unique if l.price_eur and l.price_eur <= 1200]
    log.info("Spotahome: %d listings (≤€1200)", len(filtered))

    # Enrich each listing with lat/lng from its detail page
    with httpx.Client(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
        for l in filtered:
            try:
                resp = client.get(l.url)
                if resp.status_code == 200:
                    lat, lng = _extract_coords(resp.text)
                    if lat and lng:
                        l.lat = lat
                        l.lng = lng
                time.sleep(0.5)
            except Exception as exc:
                log.debug("Spotahome coords fetch error %s: %s", l.external_id, exc)

    return filtered


def _extract_coords(html: str):
    # Coords appear as: "coord",[ref1,ref2],LNG,LAT in the page data
    m = re.search(r'"coord",\[[^\]]+\],([-0-9.]+),([-0-9.]+)', html)
    if m:
        return float(m.group(2)), float(m.group(1))  # lat, lng
    return None, None


def _parse_page(html: str) -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    listings = []

    # Find all price elements — each represents one listing card
    price_els = soup.find_all(class_=re.compile(r"price__amount"))
    for price_el in price_els:
        try:
            # Walk up to find the card container with a link
            parent = price_el
            link = None
            for _ in range(12):
                parent = parent.parent
                if parent is None:
                    break
                link = parent.find("a", href=True)
                if link:
                    break
            if not link:
                continue

            href = link.get("href", "")
            if not href:
                continue
            url = href if href.startswith("http") else BASE_URL + href

            # Extract listing ID from URL
            uid_m = re.search(r"/(\d+)(?:\?|$)", href)
            uid = uid_m.group(1) if uid_m else href.split("/")[-1].split("?")[0]
            if not uid:
                continue

            # Parse price
            price_text = price_el.get_text().replace("€", "").replace(",", "").strip()
            nums = re.findall(r"\d+", price_text)
            if not nums:
                continue
            price = int(nums[0])
            if price <= 0:
                continue

            # Title and neighborhood
            title_el = parent.find(class_=re.compile(r"title"))
            title = title_el.get_text().strip() if title_el else ""

            # Neighborhood: extract from title "... in NEIGHBORHOOD, Madrid"
            neighborhood = "Madrid"
            neigh_m = re.search(r" in ([^,\.]+)[,\.]", title)
            if neigh_m:
                neighborhood = neigh_m.group(1).strip()

            # Image
            img = parent.find("img")
            images = [img.get("src") or img.get("data-src") or ""] if img else []
            images = [i for i in images if i]

            listings.append(Listing(
                source="spotahome",
                external_id=uid,
                url=url,
                title=title or f"Apartment in {neighborhood}",
                price_eur=price,
                neighborhood=neighborhood,
                furnished=True,
                images=images[:5],
                raw_data={"url": url, "price": price, "title": title},
            ))
        except Exception as exc:
            log.debug("Spotahome card parse error: %s", exc)

    return listings
