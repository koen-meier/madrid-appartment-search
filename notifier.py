"""
Email notifier via Resend (https://resend.com).
Sends a digest of newly found listings.
"""
import logging
import os
import httpx

log = logging.getLogger(__name__)

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
EMAIL_FROM = os.environ.get("EMAIL_FROM", "madrid-search@yourdomain.com")
EMAIL_TO = os.environ.get("EMAIL_TO", "")


def send_digest(listings: list[dict]) -> None:
    if not listings:
        return
    if not RESEND_API_KEY or not EMAIL_TO:
        log.warning("Email not configured (RESEND_API_KEY or EMAIL_TO missing)")
        return

    html = _build_html(listings)
    payload = {
        "from": EMAIL_FROM,
        "to": [EMAIL_TO],
        "subject": f"🏠 {len(listings)} new Madrid apartment{'s' if len(listings) != 1 else ''} found",
        "html": html,
    }
    try:
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        log.info("Email sent: %d listings", len(listings))
    except Exception as exc:
        log.error("Email send failed: %s", exc)


def _build_html(listings: list[dict]) -> str:
    cards = ""
    for l in listings:
        img = l["images"][0] if l.get("images") else ""
        img_tag = (
            f'<img src="{img}" style="width:100%;height:180px;object-fit:cover;border-radius:6px 6px 0 0">'
            if img else ""
        )
        source_colors = {
            "housinganywhere": "#4f46e5",
            "idealista": "#dc2626",
            "spotahome": "#ea580c",
            "fotocasa": "#16a34a",
        }
        color = source_colors.get(l.get("source", ""), "#6b7280")

        cards += f"""
        <div style="border:1px solid #e5e7eb;border-radius:8px;margin-bottom:16px;overflow:hidden;font-family:sans-serif">
          {img_tag}
          <div style="padding:12px 16px">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
              <span style="background:{color};color:white;font-size:11px;padding:2px 8px;border-radius:99px">{l.get("source","").upper()}</span>
              <strong style="font-size:18px;color:#111">€{l.get("price_eur","?")}/mo</strong>
            </div>
            <div style="font-size:14px;font-weight:600;margin-bottom:2px">{l.get("title","")}</div>
            <div style="font-size:13px;color:#6b7280;margin-bottom:8px">
              {l.get("neighborhood","")}{" · " + str(l["area_m2"]) + " m²" if l.get("area_m2") else ""}
            </div>
            <a href="{l.get("url","")}" style="background:#111;color:white;padding:8px 14px;border-radius:6px;text-decoration:none;font-size:13px">
              View listing →
            </a>
          </div>
        </div>"""

    return f"""
    <div style="max-width:600px;margin:0 auto;padding:24px;font-family:sans-serif">
      <h2 style="margin-bottom:4px">🏠 New Madrid apartments</h2>
      <p style="color:#6b7280;margin-top:0;margin-bottom:20px">
        {len(listings)} new listing{"s" if len(listings) != 1 else ""} found matching your criteria
        (furnished, ≤€1000/mo, August–December, ≤45 min from IE Tower)
      </p>
      {cards}
      <p style="color:#9ca3af;font-size:12px;margin-top:24px">
        Rate listings and see the full dashboard at your Render URL.
        You receive this email whenever new matches are found (checked every 4 hours).
      </p>
    </div>"""
