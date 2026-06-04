from dataclasses import dataclass, field
from datetime import date
from typing import Optional
import httpx

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Neighbourhoods reachable from Begoña (line 10) in ≤45 min
TARGET_NEIGHBORHOODS = [
    "tetuán", "tetuan",
    "chamartín", "chamartin",
    "chamberí", "chamberi",
    "malasaña", "malasana",
    "chueca",
    "salamanca",
    "alonso martínez", "alonso martinez",
    "prosperidad",
    "almagro",
    "ríos rosas", "rios rosas",
    "cuatro caminos",
    "ciudad universitaria",
    "moncloa",
    "argüelles", "arguelles",
    "lavapiés", "lavapies",
    "centro",
    "universidad",
    "tribunal",
    "retiro",
    "lista",
    "goya",
    "velázquez", "velazquez",
    "nuevos ministerios",
    "castillejos",
    "vallehermoso",
    "cuatro torres",
]


@dataclass
class Listing:
    source: str
    external_id: str
    url: str
    title: str
    price_eur: int
    neighborhood: str
    furnished: bool = True
    area_m2: Optional[int] = None
    address: Optional[str] = None
    available_from: Optional[date] = None
    description: Optional[str] = None
    images: list = field(default_factory=list)
    lat: Optional[float] = None
    lng: Optional[float] = None
    raw_data: dict = field(default_factory=dict)


def make_client(timeout: int = 20) -> httpx.Client:
    return httpx.Client(headers=HEADERS, timeout=timeout, follow_redirects=True)
