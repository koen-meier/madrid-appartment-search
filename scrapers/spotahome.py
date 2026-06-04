"""
Spotahome scraper — parses __NEXT_DATA__ + HTML cards from search page.
"""
import json
import logging
import re
from bs4 import BeautifulSoup
from .base import Listing, make_client

log = logging.getLogger(__name__)

SEARCH_URLS = [
    "https://www.spotahome.com/s/madrid/for-rent:apartments",
    "https://www.spotahome.com/s/madrid",
]


def scrape() -> list[Listing]:
    listings = []
    with make_client() as client:
        for url in SEARCH_URLS:
            try:
                resp = client.get(url)
                resp.raise_for_status()
                found = _parse_page(resp.text)
                if found:
                    listings.extend(found)
                    break
            except Exception as exc:
                log.warning("Spotahome fetch failed (%s): %s", url, exc)

    filtered = [l for l in listings if l.price_eur and l.price_eur <= 1000]
    log.info("Spotahome: %d listings", len(filtered))
    return filtered


def _parse_page(html: str) -> list[Listing]:
    # Try __NEXT_DATA__
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            items = _deep_find_listings(data)
            if items:
                log.info("Spotahome: found %d items in __NEXT_DATA__", len(items))
                return [l for item in items if (l := _parse_item(item))]
        except Exception as exc:
            log.warning("Spotahome __NEXT_DATA__ error: %s", exc)

    # Fallback: HTML cards
    return _parse_html_cards(html)


def _deep_find_listings(obj, depth=0) -> list:
    if depth > 6:
        return []
    if isinstance(obj, list) and len(obj) > 2 and isinstance(obj[0], dict):
        if any(k in obj[0] for k in ("price", "priceInfo", "id", "homeId")):
            return obj
    if isinstance(obj, dict):
        for v in obj.values():
            r = _deep_find_listings(v, depth + 1)
            if r:
                return r
    return []


def _parse_html_cards(html: str) -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    listings = []

    for card in soup.select("[class*='home-card'], [class*='HomeCard'], [class*='listing'], article"):
        try:
            link = card.select_one("a[href*='/flat'], a[href*='/home'], a[href*='/apartment']")
            if not link:
                link = card.select_one("a[href]")
            if not link:
                continue

            href = link.get("href", "")
            url = href if href.startswith("http") else f"https://www.spotahome.com{href}"
            uid = href.rstrip("/").split("/")[-1].split("?")[0]

            price_el = card.select_one("[class*='price'], [class*='Price']")
            if not price_el:
                continue
            price_nums = re.findall(r"\d+", price_el.get_text().replace(".", "").replace(",", ""))
            if not price_nums:
                continue
            price = int(price_nums[0])
            if price <= 0 or price > 1100:
                continue

            title_el = card.select_one("h2, h3, [class*='title'], [class*='Title']")
            title = title_el.get_text(strip=True) if title_el else f"Apartment {uid}"

            location_el = card.select_one("[class*='location'], [class*='Location'], [class*='zone'], [class*='area']")
            neighborhood = location_el.get_text(strip=True) if location_el else "Madrid"

            images = []
            for img in card.select("img"):
                src = img.get("src") or img.get("data-src") or ""
                if src and "spotahome" in src:
                    images.append(src)

            listings.append(Listing(
                source="spotahome",
                external_id=uid or url,
                url=url,
                title=title,
                price_eur=price,
                neighborhood=neighborhood,
                furnished=True,
                images=images[:5],
                raw_data={"url": url},
            ))
        except Exception as exc:
            log.debug("Spotahome card parse error: %s", exc)

    return listings


def _parse_item(item: dict) -> Listing | None:
    try:
        price_info = item.get("price") or item.get("priceInfo") or item.get("pricing") or {}
        if isinstance(price_info, dict):
            price = int(price_info.get("amount") or price_info.get("value") or price_info.get("price") or 0)
        else:
            price = int(price_info)
        if price <= 0 or price > 1100:
            return None

        uid = str(item.get("id") or item.get("homeId") or item.get("slug") or "")
        slug = item.get("slug") or uid
        url = f"https://www.spotahome.com/en/flat-and-house-for-rent/{slug}" if slug else ""

        location = item.get("location") or {}
        neighborhood = (
            item.get("neighborhood") or item.get("area") or item.get("zone")
            or (location.get("neighborhood") if isinstance(location, dict) else None)
            or "Madrid"
        )

        images = []
        for img in item.get("images") or item.get("photos") or item.get("media") or []:
            src = img.get("url") or img.get("src") or "" if isinstance(img, dict) else img
            if src:
                images.append(src)

        return Listing(
            source="spotahome",
            external_id=uid,
            url=url,
            title=item.get("title") or item.get("name") or f"Apartment in {neighborhood}",
            price_eur=price,
            neighborhood=neighborhood,
            area_m2=item.get("squareMeters") or item.get("area") or item.get("size"),
            furnished=True,
            description=item.get("description") or "",
            images=images[:10],
            lat=(location.get("lat") if isinstance(location, dict) else None) or item.get("lat"),
            lng=(location.get("lng") if isinstance(location, dict) else None) or item.get("lng"),
            raw_data=item,
        )
    except Exception as exc:
        log.warning("Spotahome item parse error: %s", exc)
        return None
