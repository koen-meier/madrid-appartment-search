"""
Main entry point — runs all scrapers, saves new listings, sends email digest.
Called by the Render cron job every 4 hours.
"""
import logging
import sys
from scrapers import housinganywhere, idealista, spotahome, fotocasa
import db
import notifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

SCRAPERS = [
    housinganywhere.scrape,
    idealista.scrape,
    spotahome.scrape,
    fotocasa.scrape,
]


def run():
    log.info("=== Madrid apartment search run started ===")
    new_ids = []

    for scrape_fn in SCRAPERS:
        source_name = scrape_fn.__module__.split(".")[-1]
        log.info("Running scraper: %s", source_name)

        try:
            listings = scrape_fn()
        except Exception as exc:
            log.error("Scraper %s crashed: %s", source_name, exc)
            continue

        existing = db.get_existing_ids(source_name)

        for listing in listings:
            is_new = listing.external_id not in existing
            uid = db.upsert_listing(listing)
            if uid and is_new:
                new_ids.append(uid)
                log.info("NEW %s/%s €%d %s", source_name, listing.external_id, listing.price_eur, listing.neighborhood)

    log.info("Total new listings this run: %d", len(new_ids))

    if new_ids:
        new_rows = db.get_new_listings(new_ids)
        notifier.send_digest(new_rows)

    log.info("=== Run complete ===")


if __name__ == "__main__":
    run()
