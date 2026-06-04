"""
Idealista scraper via Apify igolaizola~idealista-scraper actor.
Handles anti-bot automatically. Requires APIFY_TOKEN env var.
"""
import logging
import os
import time
import httpx
from .base import Listing

log = logging.getLogger(__name__)

APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")
ACTOR_ID = "lukass~idealista-scraper"
RUN_URL = f"https://api.apify.com/v2/acts/{ACTOR_ID}/runs"

# Madrid furnished rentals under €1000 — temporal (mid-term) + long-term
SEARCH_URLS = [
    "https://www.idealista.com/alquiler-viviendas/madrid-madrid/con-precio-hasta_1000,amueblado/",
    "https://www.idealista.com/alquiler-viviendas/madrid-madrid/con-precio-hasta_1000,amueblado,alquiler-temporal/",
]


def scrape() -> list[Listing]:
    if not APIFY_TOKEN:
        log.warning("APIFY_TOKEN not set — skipping Idealista")
        return []

    headers = {"Authorization": f"Bearer {APIFY_TOKEN}"}

    try:
        resp = httpx.post(
            RUN_URL,
            headers=headers,
            json={
                "country": "es",
                "operation": "rent",
                "district": "Madrid",
                "propertyType": "homes",
                "maxItems": 150,
                "startUrl": [{"url": u} for u in SEARCH_URLS],
            },
            timeout=30,
        )
        resp.raise_for_status()
        run_id = resp.json()["data"]["id"]
        log.info("Idealista Apify run started: %s", run_id)
    except Exception as exc:
        log.error("Idealista Apify start failed: %s", exc)
        return []

    # Poll until done (max 4 min)
    for _ in range(24):
        time.sleep(10)
        try:
            status_resp = httpx.get(
                f"https://api.apify.com/v2/actor-runs/{run_id}",
                headers=headers, timeout=10,
            )
            status = status_resp.json()["data"]["status"]
            log.info("Idealista run status: %s", status)
            if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                break
        except Exception:
            pass

    try:
        items_resp = httpx.get(
            f"https://api.apify.com/v2/actor-runs/{run_id}/dataset/items",
            headers=headers, params={"limit": 200}, timeout=30,
        )
        items_resp.raise_for_status()
        items = items_resp.json()
    except Exception as exc:
        log.error("Idealista Apify fetch failed: %s", exc)
        return []

    log.info("Idealista raw items: %d", len(items))
    listings = [l for item in items if (l := _parse(item))]
    log.info("Idealista: %d listings after filter", len(listings))
    return listings


def _parse(item: dict) -> Listing | None:
    try:
        price = item.get("price") or item.get("priceInfo", {}).get("price") or 0
        price = int(str(price).replace(".", "").replace(",", "").split()[0])
        if price <= 0 or price > 1100:  # slight buffer
            return None

        uid = str(item.get("propertyCode") or item.get("id") or "")
        url = item.get("url") or item.get("detailUrl") or ""
        if url and not url.startswith("http"):
            url = "https://www.idealista.com" + url

        neighborhood = (
            item.get("neighborhood")
            or item.get("district")
            or item.get("municipality")
            or "Madrid"
        )

        images = []
        for img in item.get("images") or item.get("photos") or []:
            src = img.get("url") or img.get("src") or "" if isinstance(img, dict) else img
            if src:
                images.append(src)

        return Listing(
            source="idealista",
            external_id=uid,
            url=url,
            title=item.get("suggestedTexts", {}).get("title") or item.get("title") or f"Apt in {neighborhood}",
            price_eur=price,
            neighborhood=neighborhood,
            area_m2=item.get("size") or item.get("area"),
            furnished=True,
            description=item.get("description") or "",
            images=images[:10],
            lat=item.get("latitude"),
            lng=item.get("longitude"),
            raw_data=item,
        )
    except Exception as exc:
        log.warning("Idealista parse error: %s", exc)
        return None
