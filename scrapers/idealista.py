"""
Idealista — Apify actor scraper (bypasses DataDome bot protection).
Uses epctex/idealista-scraper which runs on residential IPs.
"""
import json
import logging
import os
import time
import httpx
from .base import Listing

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.idealista.com/alquiler-viviendas/madrid-madrid/con-precio-hasta_1000,amueblado/"
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")

# epctex → 404, dtrungtin → 403 (private). lukass needs residential proxy + correct schema.
ACTORS = [
    "lukass/idealista-scraper",
]


def scrape() -> list[Listing]:
    if not APIFY_TOKEN:
        log.warning("Idealista: APIFY_TOKEN not set, skipping")
        return []

    for actor in ACTORS:
        listings = _run_actor(actor)
        if listings:
            log.info("Idealista: %d listings via %s", len(listings), actor)
            return listings
        log.info("Idealista: actor %s returned 0, trying next", actor)

    log.warning("Idealista: all actors returned 0")
    return []


def _run_actor(actor_id: str) -> list[Listing]:
    base = "https://api.apify.com/v2"
    headers = {"Authorization": f"Bearer {APIFY_TOKEN}", "Content-Type": "application/json"}

    # Actor-specific input configs
    if "epctex" in actor_id:
        payload = {
            "startUrls": [{"url": SEARCH_URL}],
            "maxItems": 50,
            "proxyConfiguration": {"useApifyProxy": True},
        }
    elif "dtrungtin" in actor_id:
        payload = {
            "startUrls": [{"url": SEARCH_URL}],
            "maxItems": 50,
        }
    else:
        # lukass — requires country, operation, proxy (residential IPs)
        payload = {
            "country": "es",
            "operation": "rent",
            "district": "Madrid",
            "propertyType": "homes",
            "maxItems": 50,
            "proxy": {
                "useApifyProxy": True,
                "apifyProxyGroups": ["RESIDENTIAL"],
            },
        }

    try:
        with httpx.Client(timeout=60) as client:
            # Start the actor run
            actor_slug = actor_id.replace("/", "~")
            r = client.post(
                f"{base}/acts/{actor_slug}/runs",
                headers=headers,
                json=payload,
                params={"waitForFinish": 120},
            )
            log.info("Idealista Apify %s: start status=%d", actor_id, r.status_code)
            if r.status_code not in (200, 201):
                log.info("Idealista Apify %s response: %s", actor_id, r.text[:200])
                return []

            run_data = r.json()
            run_id = run_data.get("data", {}).get("id") or run_data.get("id")
            if not run_id:
                log.info("Idealista Apify %s: no run id in %s", actor_id, str(run_data)[:200])
                return []

            # Poll until done (waitForFinish handles this but let's be safe)
            for _ in range(20):
                status_r = client.get(f"{base}/actor-runs/{run_id}", headers=headers)
                status = status_r.json().get("data", {}).get("status", "")
                log.info("Idealista Apify %s run %s: %s", actor_id, run_id, status)
                if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                    break
                time.sleep(10)

            if status != "SUCCEEDED":
                log.warning("Idealista Apify %s: run ended with status %s", actor_id, status)
                return []

            # Get results from default dataset
            dataset_id = status_r.json().get("data", {}).get("defaultDatasetId", "")
            if not dataset_id:
                return []

            items_r = client.get(
                f"{base}/datasets/{dataset_id}/items",
                headers=headers,
                params={"format": "json", "limit": 200},
            )
            items = items_r.json()
            log.info("Idealista Apify %s: %d items in dataset", actor_id, len(items))

            listings = []
            for item in items:
                l = _parse_item(item)
                if l:
                    listings.append(l)
            return listings

    except Exception as exc:
        log.error("Idealista Apify %s error: %s", actor_id, exc)
        return []


def _parse_item(item: dict) -> "Listing | None":
    try:
        # Handle various actor output formats
        price = (
            item.get("price")
            or item.get("priceInfo", {}).get("price")
            or item.get("monthlyPrice")
            or 0
        )
        if isinstance(price, str):
            price = int("".join(filter(str.isdigit, price)) or "0")
        price = int(price)
        if price <= 0 or price > 1100:
            return None

        uid = str(
            item.get("propertyCode")
            or item.get("id")
            or item.get("listingId")
            or item.get("url", "").rstrip("/").split("/")[-1]
            or ""
        )
        if not uid:
            return None

        url = item.get("url") or item.get("detailUrl") or ""
        if url and not url.startswith("http"):
            url = "https://www.idealista.com" + url

        neighborhood = (
            item.get("neighborhood")
            or item.get("district")
            or item.get("location")
            or "Madrid"
        )

        images = []
        for img in item.get("images") or item.get("photos") or []:
            src = (img.get("url") or img.get("src") or "") if isinstance(img, dict) else str(img)
            if src:
                images.append(src)

        return Listing(
            source="idealista",
            external_id=uid,
            url=url,
            title=(
                item.get("suggestedTexts", {}).get("title")
                or item.get("title")
                or item.get("description", "")[:80]
                or f"Apartment in {neighborhood}"
            ),
            price_eur=price,
            neighborhood=neighborhood,
            area_m2=item.get("size") or item.get("area"),
            furnished=True,
            description=item.get("description") or "",
            images=images[:10],
            lat=item.get("latitude") or item.get("lat"),
            lng=item.get("longitude") or item.get("lng"),
            raw_data=item,
        )
    except Exception as exc:
        log.debug("Idealista parse error: %s", exc)
        return None
