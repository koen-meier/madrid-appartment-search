"""
Supabase helpers — save listings, check for duplicates.
Uses the REST API directly so no extra SDK is needed beyond httpx.
"""
import logging
import os
from typing import Optional
import httpx
from scrapers.base import Listing

log = logging.getLogger(__name__)

SUPABASE_URL = os.environ["SUPABASE_URL"]          # e.g. https://xxxx.supabase.co
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]  # service role key (server-side only)

_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}


def _url(path: str) -> str:
    return f"{SUPABASE_URL}/rest/v1/{path}"


def upsert_listing(listing: Listing) -> Optional[str]:
    """Insert or update a listing. Returns the UUID if successful, None on error."""
    payload = {
        "external_id": listing.external_id,
        "source": listing.source,
        "url": listing.url,
        "title": listing.title,
        "price_eur": listing.price_eur,
        "neighborhood": listing.neighborhood,
        "furnished": listing.furnished,
        "area_m2": listing.area_m2,
        "address": listing.address,
        "available_from": listing.available_from.isoformat() if listing.available_from else None,
        "description": listing.description,
        "images": listing.images[:10],  # cap at 10 images
        "lat": listing.lat,
        "lng": listing.lng,
        "raw_data": listing.raw_data,
    }
    try:
        resp = httpx.post(
            _url("listings"),
            headers={**_HEADERS, "Prefer": "return=representation,resolution=merge-duplicates"},
            params={"on_conflict": "source,external_id"},
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        rows = resp.json()
        return rows[0]["id"] if rows else None
    except Exception as exc:
        log.error("DB upsert failed for %s/%s: %s", listing.source, listing.external_id, exc)
        return None


def get_existing_ids(source: str) -> set[str]:
    """Return all external_ids already stored for a given source."""
    try:
        resp = httpx.get(
            _url("listings"),
            headers=_HEADERS,
            params={"select": "external_id", "source": f"eq.{source}", "limit": 10000},
            timeout=10,
        )
        resp.raise_for_status()
        return {row["external_id"] for row in resp.json()}
    except Exception as exc:
        log.error("DB get_existing_ids failed for %s: %s", source, exc)
        return set()


def get_new_listings(since_run_ids: list[str]) -> list[dict]:
    """Return full listing rows for a list of UUIDs (freshly inserted this run)."""
    if not since_run_ids:
        return []
    id_list = ",".join(f'"{i}"' for i in since_run_ids)
    try:
        resp = httpx.get(
            _url("listings"),
            headers=_HEADERS,
            params={"select": "*", "id": f"in.({id_list})"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.error("DB get_new_listings failed: %s", exc)
        return []
