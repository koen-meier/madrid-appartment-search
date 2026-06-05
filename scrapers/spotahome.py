"""
Spotahome scraper — Playwright for JS rendering, extracts __NEXT_DATA__ or DOM.
"""
import json
import logging
import re
from .base import Listing

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.spotahome.com/s/madrid/for-rent:apartments"


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

            # Dismiss cookie banner (CookieYes)
            for selector in ["button.cky-btn-accept", "button[aria-label='Accept All']",
                              "button:has-text('Accept All')", "button:has-text('Aceptar')"]:
                try:
                    page.click(selector, timeout=3000)
                    page.wait_for_timeout(2000)
                    break
                except Exception:
                    pass

            # Wait for listing cards
            try:
                page.wait_for_selector("[class*='home-card'], [class*='HomeCard'], [class*='listing']", timeout=8000)
            except Exception:
                pass

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
                    log.info("Spotahome: %d from __NEXT_DATA__", len(listings))

            if not listings:
                title = page.title()
                sample = page.evaluate("() => document.body.innerHTML.slice(0, 3000)")
                log.info("Spotahome page title: %s", title)
                log.info("Spotahome HTML sample: %s", sample)

                items_json = page.evaluate("""
                    () => {
                        const selectors = ['[class*="home-card"]','[class*="HomeCard"]','[class*="HomesCard"]',
                                           '[data-testid*="home"]','[class*="listing-card"]','article'];
                        let cards = [];
                        for (const sel of selectors) {
                            const found = document.querySelectorAll(sel);
                            if (found.length > 1) { cards = Array.from(found); break; }
                        }
                        return cards.slice(0,60).map(card => {
                            const link = card.querySelector('a[href]');
                            const price = card.querySelector('[class*="price"],[class*="Price"],[class*="amount"]');
                            const title = card.querySelector('h2,h3,h4,[class*="title"],[class*="Title"]');
                            const loc = card.querySelector('[class*="zone"],[class*="area"],[class*="location"],[class*="city"]');
                            const img = card.querySelector('img');
                            return {
                                url: link ? link.href : '',
                                priceText: price ? price.innerText : '',
                                title: title ? title.innerText : '',
                                neighborhood: loc ? loc.innerText : 'Madrid',
                                img: img ? (img.src || img.getAttribute('data-src') || '') : '',
                            };
                        }).filter(x => x.url && x.priceText);
                    }
                """)
                listings = [l for item in (items_json or []) if (l := _parse_dom_item(item))]
                log.info("Spotahome: %d from DOM", len(listings))

        except Exception as exc:
            log.error("Spotahome scrape error: %s", exc)
        finally:
            browser.close()

    filtered = [l for l in listings if l.price_eur and l.price_eur <= 1000]
    log.info("Spotahome: %d listings after filter", len(filtered))
    return filtered


def _deep_find_listings(obj, depth=0) -> list:
    if depth > 7:
        return []
    if isinstance(obj, list) and len(obj) > 1 and isinstance(obj[0], dict):
        if any(k in obj[0] for k in ("price", "priceInfo", "id", "homeId", "slug")):
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
        return Listing(
            source="spotahome",
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
        log.debug("Spotahome DOM parse error: %s", exc)
        return None


def _parse_item(item: dict) -> Listing | None:
    try:
        price_info = item.get("price") or item.get("priceInfo") or item.get("pricing") or {}
        price = int(price_info.get("amount") or price_info.get("value") or price_info.get("price") or 0) if isinstance(price_info, dict) else int(price_info or 0)
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
