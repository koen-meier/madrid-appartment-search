"""
HousingAnywhere scraper — parses listing cards from the search HTML page.
Search URL: https://housinganywhere.com/s/Madrid--Spain/furnished-apartments
"""
import json
import logging
import re
from bs4 import BeautifulSoup
from .base import Listing, make_client

log = logging.getLogger(__name__)

SEARCH_URLS = [
    "https://housinganywhere.com/s/Madrid--Spain/furnished-apartments",
    "https://housinganywhere.com/s/Madrid--Spain/apartment-for-rent",
]


def scrape() -> list[Listing]:
    listings = []
    with make_client() as client:
        for url in SEARCH_URLS:
            try:
                resp = client.get(url)
                resp.raise_for_status()
                found = _parse_page(resp.text, url)
                listings.extend(found)
                if found:
                    break
            except Exception as exc:
                log.warning("HousingAnywhere fetch failed (%s): %s", url, exc)

    # Deduplicate by external_id
    seen = set()
    unique = []
    for l in listings:
        if l.external_id not in seen:
            seen.add(l.external_id)
            unique.append(l)

    log.info("HousingAnywhere: %d listings", len(unique))
    return unique


def _parse_page(html: str, base_url: str) -> list[Listing]:
    # Try __NEXT_DATA__ first
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            items = _extract_items(data)
            if items:
                log.info("HousingAnywhere: found %d items in __NEXT_DATA__", len(items))
                return [l for item in items if (l := _parse_item(item))]
        except Exception as exc:
            log.warning("HousingAnywhere __NEXT_DATA__ parse error: %s", exc)

    # Fallback: parse HTML cards
    return _parse_html_cards(html)


def _extract_items(data: dict, depth: int = 0) -> list:
    if depth > 6:
        return []
    if isinstance(data, list) and data and isinstance(data[0], dict):
        if any(k in data[0] for k in ("price", "rent", "monthlyPrice", "id")):
            return data
    if isinstance(data, dict):
        for v in data.values():
            result = _extract_items(v, depth + 1)
            if result:
                return result
    return []


def _parse_html_cards(html: str) -> list[Listing]:
    """Parse listing cards from rendered HTML."""
    soup = BeautifulSoup(html, "lxml")
    listings = []

    for card in soup.select("article, [data-testid*='listing'], [class*='ListingCard'], [class*='listing-card']"):
        try:
            link = card.select_one("a[href*='/rooms/'], a[href*='/listing/'], a[href*='/apartment/']")
            if not link:
                continue
            href = link.get("href", "")
            url = href if href.startswith("http") else f"https://housinganywhere.com{href}"
            uid = href.rstrip("/").split("/")[-1]

            price_el = card.select_one("[class*='price'], [data-testid*='price']")
            if not price_el:
                continue
            price_text = price_el.get_text()
            price_match = re.search(r"(\d[\d,.]+)", price_text.replace(".", "").replace(",", ""))
            if not price_match:
                continue
            price = int(price_match.group(1))
            if price <= 0 or price > 1100:
                continue

            title_el = card.select_one("h2, h3, [class*='title']")
            title = title_el.get_text(strip=True) if title_el else f"Apartment {uid}"

            location_el = card.select_one("[class*='location'], [class*='neighborhood'], [class*='address']")
            neighborhood = location_el.get_text(strip=True) if location_el else "Madrid"

            images = []
            for img in card.select("img[src*='housinganywhere'], img[data-src*='housinganywhere']"):
                src = img.get("src") or img.get("data-src") or ""
                if src:
                    images.append(src)

            listings.append(Listing(
                source="housinganywhere",
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
            log.debug("HousingAnywhere card parse error: %s", exc)

    return listings


def _parse_item(item: dict) -> Listing | None:
    try:
        price_info = item.get("price") or item.get("monthlyPrice") or item.get("rent") or {}
        if isinstance(price_info, dict):
            price = int(price_info.get("amount") or price_info.get("value") or 0)
        else:
            price = int(price_info)
        if price <= 0 or price > 1100:
            return None

        uid = str(item.get("id") or item.get("slug") or "")
        slug = item.get("slug") or uid
        url = f"https://housinganywhere.com/listing/{slug}" if slug else ""

        neighborhood = (
            item.get("neighborhood") or item.get("area")
            or item.get("district") or item.get("city", "Madrid")
        )

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
