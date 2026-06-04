"""
Idealista scraper — via Apify cloud actor.
Apify handles anti-bot (DataDome). Requires APIFY_TOKEN env var.
Actor: https://apify.com/lukass/idealista-scraper
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

# Idealista search URL for furnished rentals in Madrid under €1000, mid-term
SEARCH_URL = (
    "https://www.idealista.com/en/alquiler-viviendas/madrid-madrid/"
    "con-precio-hasta_1000,amueblado,alquiler-temporal/"
)


def scrape() -> list[Listing]:
    if not APIFY_TOKEN:
        log.warning("APIFY_TOKEN not set — skipping Idealista")
        return []

    headers = {"Authorization": f"Bearer {APIFY_TOKEN}"}

    # Start actor run
    try:
        resp = httpx.post(
            RUN_URL,
            headers=headers,
            json={
                "startUrls": [{"url": SEARCH_URL}],
                "maxItems": 100,
                "proxyConfiguration": {"useApifyProxy": True},
            },
            timeout=30,
        )
        resp.raise_for_status()
        run_id = resp.json()["data"]["id"]
    except Exception as exc:
        log.error("Idealista Apify start failed: %s", exc)
        return []

    # Poll until done (max 3 min)
    dataset_url = f"https://api.apify.com/v2/actor-runs/{run_id}/dataset/items"
    for _ in range(18):
        time.sleep(10)
        try:
            status_resp = httpx.get(
                f"https://api.apify.com/v2/actor-runs/{run_id}",
                headers=headers,
                timeout=10,
            )
            status = status_resp.json()["data"]["status"]
            if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                break
        except Exception:
            pass

    # Fetch results
    try:
        items_resp = httpx.get(dataset_url, headers=headers, params={"limit": 200}, timeout=30)
        items_resp.raise_for_status()
        items = items_resp.json()
    except Exception as exc:
        log.error("Idealista Apify fetch failed: %s", exc)
        return []

    listings = [l for item in items if (l := _parse(item))]
    log.info("Idealista: %d listings", len(listings))
    return listings


def _parse(item: dict) -> Listing | None:
    try:
        price_raw = item.get("price") or item.get("priceInfo", {}).get("amount") or 0
        price = int(str(price_raw).replace(".", "").replace(",", "").split()[0])
        if price <= 0 or price > 1000:
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
            if isinstance(img, str):
                images.append(img)
            elif isinstance(img, dict):
                images.append(img.get("url") or img.get("src") or "")

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
            images=[i for i in images if i],
            lat=item.get("latitude"),
            lng=item.get("longitude"),
            raw_data=item,
        )
    except Exception as exc:
        log.warning("Idealista parse error: %s | item: %s", exc, item)
        return None
