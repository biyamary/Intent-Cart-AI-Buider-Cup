"""Fetch public product pages and read only the facts a page publishes about itself.

Commerce facts (title, price, currency, image, stock, rating) come from the
page's structured data, in this order of trust:

  1. schema.org Product JSON-LD
  2. Shopify's public `/products/<handle>.js` endpoint (common on independent stores)
  3. OpenGraph / product meta tags

A page without a title and an INR price is not treated as a product. The model
never supplies these values; search results only nominate URLs.

Every request is restricted to public https hosts: each redirect hop is resolved
and rejected if any address is not globally routable. This is a check-then-connect
guard (a DNS rebinding window remains); keep it behind an egress proxy in production.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

MAX_BYTES = 2_000_000
MAX_REDIRECTS = 5
TIMEOUT_S = 8.0
USER_AGENT = "Mozilla/5.0 (compatible; IntentCart/0.1; shopping assistant prototype)"
HTML_TYPES = {"text/html", "application/xhtml+xml"}
JSON_TYPES = {"application/json", "text/javascript", "application/javascript"}
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 6_000_000
GROUNDING_REDIRECT_HOSTS = {"vertexaisearch.cloud.google.com"}


@dataclass
class FetchResult:
    ok: bool
    url: str
    final_url: str | None = None
    status: int | None = None
    content_type: str = ""
    body: str = ""
    error: str | None = None
    data: bytes = b""


@dataclass
class PageFacts:
    """Structured facts read from a product page. Prices are integer paise."""

    url: str
    title: str = ""
    price_minor: int | None = None
    currency: str | None = None
    image_url: str | None = None
    availability: str = "unknown"
    rating: float | None = None
    rating_count: int | None = None
    seller_name: str = ""
    colour: str = ""
    verification: str = ""
    fetched_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    @property
    def is_product(self) -> bool:
        return bool(self.title) and self.price_minor is not None and self.currency == "INR"


Fetcher = Callable[[str], Awaitable[FetchResult]]


# --------------------------------------------------------------------------- #
# URL safety
# --------------------------------------------------------------------------- #
def normalise_url(url: str) -> str | None:
    """Plain https URL on the default port, without credentials or fragment."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        return None
    if port not in (None, 443):
        return None
    host = parts.hostname.lower().rstrip(".")
    return urlunsplit(("https", host, parts.path or "/", parts.query, ""))


def host_of(url: str) -> str:
    try:
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
    return host.removeprefix("www.")


async def is_public_host(host: str) -> bool:
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, 443, type=socket.SOCK_STREAM
        )
    except (socket.gaierror, UnicodeError, OSError):
        return False
    if not infos:
        return False
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if not address.is_global:
            return False
    return True


async def fetch_public(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    accept: str = "text/html,application/xhtml+xml",
    host_check: Callable[[str], Awaitable[bool]] = is_public_host,
    allowed_types: set[str] | None = None,
    max_bytes: int = MAX_BYTES,
) -> FetchResult:
    """GET a public https page, following redirects by hand. Never raises."""
    current = normalise_url(url)
    if current is None:
        return FetchResult(False, url, error="invalid_url")
    allowed_types = allowed_types or (HTML_TYPES | JSON_TYPES)
    owns = client is None
    client = client or httpx.AsyncClient(
        timeout=TIMEOUT_S, follow_redirects=False, headers={"User-Agent": USER_AGENT}
    )
    try:
        for _ in range(MAX_REDIRECTS + 1):
            host = urlsplit(current).hostname or ""
            if not await host_check(host):
                return FetchResult(False, url, final_url=current, error="blocked_host")
            try:
                async with client.stream("GET", current, headers={"Accept": accept}) as resp:
                    if 300 <= resp.status_code < 400:
                        location = resp.headers.get("location")
                        nxt = normalise_url(urljoin(current, location)) if location else None
                        if nxt is None:
                            return FetchResult(False, url, current, resp.status_code, error="bad_redirect")
                        current = nxt
                        continue
                    ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                    if resp.status_code >= 400:
                        return FetchResult(False, url, current, resp.status_code, ctype, error=f"http_{resp.status_code}")
                    if ctype not in allowed_types:
                        return FetchResult(False, url, current, resp.status_code, ctype, error="unsupported_type")
                    body = bytearray()
                    async for chunk in resp.aiter_bytes():
                        body.extend(chunk)
                        if len(body) >= max_bytes:
                            break
                    if ctype in IMAGE_TYPES:
                        if len(body) >= max_bytes:
                            return FetchResult(False, url, current, resp.status_code, ctype, error="too_large")
                        return FetchResult(True, url, current, resp.status_code, ctype, data=bytes(body))
                    text = bytes(body[:max_bytes]).decode(resp.charset_encoding or "utf-8", "replace")
                    return FetchResult(True, url, current, resp.status_code, ctype, text)
            except httpx.HTTPError as error:
                return FetchResult(False, url, current, error=f"network_{type(error).__name__}")
        return FetchResult(False, url, current, error="too_many_redirects")
    finally:
        if owns:
            await client.aclose()


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
class _HeadParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.ld_json: list[str] = []
        self.canonical: str | None = None
        self.title = ""
        self._in_ld = False
        self._in_title = False
        self._buffer: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = {key.lower(): (value or "") for key, value in attrs}
        if tag == "meta":
            key = (values.get("property") or values.get("name") or values.get("itemprop") or "").lower()
            if key and "content" in values and key not in self.meta:
                self.meta[key] = values["content"].strip()
        elif tag == "link" and "canonical" in values.get("rel", "").lower().split():
            self.canonical = values.get("href") or None
        elif tag == "script" and values.get("type", "").lower() == "application/ld+json":
            self._in_ld, self._buffer = True, []
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "script" and self._in_ld:
            self.ld_json.append("".join(self._buffer))
            self._in_ld = False
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_ld:
            self._buffer.append(data)
        elif self._in_title and len(self.title) < 300:
            self.title += data


def parse_price(value: Any) -> int | None:
    """Rupee amount ('4,290.00', 4290, '₹ 4,290') to paise; None if unclear."""
    if isinstance(value, bool) or value is None:
        return None
    text = re.sub(r"[^\d.,]", "", str(value)).replace(",", "")
    if not text or text.count(".") > 1:
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    if amount <= 0 or amount > 10_000_000:
        return None
    return int((amount * 100).to_integral_value())


def _availability(value: Any) -> str:
    text = str(value or "").lower()
    if not text:
        return "unknown"
    if "outofstock" in text.replace(" ", "").replace("_", "") or text in {"oos", "soldout", "sold out"}:
        return "out_of_stock"
    if "instock" in text.replace(" ", "").replace("_", "") or text in {"available", "true"}:
        return "in_stock"
    return "unknown"


def _absolute_image(value: Any, base: str) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = value.get("url") or value.get("contentUrl")
    if not isinstance(value, str) or not value.strip():
        return None
    url = value.strip()
    url = "https:" + url if url.startswith("//") else urljoin(base, url)
    return url if url.startswith("https://") else None


def _iter_ld(node: Any):
    if isinstance(node, list):
        for item in node:
            yield from _iter_ld(item)
    elif isinstance(node, dict):
        yield node
        if "@graph" in node:
            yield from _iter_ld(node["@graph"])


def _is_type(node: dict, name: str) -> bool:
    kind = node.get("@type")
    kinds = kind if isinstance(kind, list) else [kind]
    return any(isinstance(k, str) and k.lower() == name.lower() for k in kinds)


def _text(value: Any, limit: int = 200) -> str:
    if isinstance(value, dict):
        value = value.get("name", "")
    if isinstance(value, list):
        value = value[0] if value else ""
    return unescape(str(value or "")).strip()[:limit]


def _from_json_ld(blocks: list[str], facts: PageFacts) -> bool:
    for raw in blocks:
        try:
            data = json.loads(raw.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        for node in _iter_ld(data):
            if not (_is_type(node, "Product") or _is_type(node, "ProductGroup")):
                continue
            facts.title = _text(node.get("name"))
            facts.image_url = _absolute_image(node.get("image"), facts.url)
            facts.colour = _text(node.get("color"), 40)
            brand = _text(node.get("brand"), 80)
            offers = node.get("offers") or []
            if not offers and _is_type(node, "ProductGroup"):
                variants = node.get("hasVariant") or []
                offers = [v.get("offers") for v in variants if isinstance(v, dict) and v.get("offers")]
            best = None
            for offer in _iter_ld(offers):
                currency = str(offer.get("priceCurrency") or "").upper() or None
                price = parse_price(offer.get("price") or offer.get("lowPrice"))
                if price is None and isinstance(offer.get("priceSpecification"), dict):
                    spec = offer["priceSpecification"]
                    price = parse_price(spec.get("price"))
                    currency = currency or (str(spec.get("priceCurrency") or "").upper() or None)
                if price is None:
                    continue
                if best is None or price < best[0]:
                    best = (price, currency, _availability(offer.get("availability")), offer)
            if best:
                facts.price_minor, facts.currency, facts.availability = best[0], best[1], best[2]
                seller = best[3].get("seller")
                facts.seller_name = _text(seller, 80) if seller else brand
            else:
                facts.seller_name = brand
            rating = node.get("aggregateRating")
            if isinstance(rating, dict):
                try:
                    value = float(rating.get("ratingValue"))
                    best_rating = float(rating.get("bestRating") or 5)
                    if 0 < best_rating and 0 <= value <= best_rating:
                        facts.rating = round(value * 5 / best_rating, 1)
                    count = rating.get("reviewCount") or rating.get("ratingCount")
                    facts.rating_count = int(count) if count is not None else None
                except (TypeError, ValueError):
                    facts.rating = facts.rating_count = None
            facts.verification = "json_ld"
            return bool(facts.title)
    return False


def _from_meta(meta: dict[str, str], facts: PageFacts) -> None:
    facts.title = facts.title or _text(meta.get("og:title"))
    facts.image_url = facts.image_url or _absolute_image(
        meta.get("og:image:secure_url") or meta.get("og:image"), facts.url
    )
    facts.seller_name = facts.seller_name or _text(meta.get("og:site_name"), 80)
    if facts.price_minor is None:
        price = parse_price(meta.get("product:price:amount") or meta.get("og:price:amount"))
        currency = (meta.get("product:price:currency") or meta.get("og:price:currency") or "").upper()
        if price is not None:
            facts.price_minor, facts.currency = price, currency or None
            facts.verification = facts.verification or "open_graph"
    if facts.availability == "unknown":
        facts.availability = _availability(
            meta.get("product:availability") or meta.get("og:availability")
        )


def parse_product_page(html: str, url: str) -> tuple[PageFacts, str | None]:
    """Return facts and the page's canonical URL (if any)."""
    parser = _HeadParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001, S110 -- keep whatever parsed before malformed markup
        pass
    facts = PageFacts(url=url)
    _from_json_ld(parser.ld_json, facts)
    _from_meta(parser.meta, facts)
    if not facts.title:
        facts.title = _text(parser.title)
    canonical = normalise_url(urljoin(url, parser.canonical)) if parser.canonical else None
    return facts, canonical


def shopify_handle_url(url: str) -> str | None:
    parts = urlsplit(url)
    match = re.search(r"/products/([A-Za-z0-9][A-Za-z0-9\-_.%]*)/?$", parts.path)
    if not match or match.group(1).endswith(".js"):
        return None
    return urlunsplit(("https", parts.netloc, f"/products/{match.group(1)}.js", "", ""))


def apply_shopify(data: dict, facts: PageFacts) -> None:
    """Shopify product JSON: integer prices are already in minor units."""
    price = data.get("price")
    replaceable = facts.price_minor is None or facts.verification == "open_graph"
    if isinstance(price, int) and price > 0 and facts.currency in (None, "INR") and replaceable:
        facts.price_minor = price
        facts.verification = "shopify"
    facts.title = facts.title or _text(data.get("title"))
    facts.image_url = facts.image_url or _absolute_image(data.get("featured_image"), facts.url)
    facts.seller_name = facts.seller_name or _text(data.get("vendor"), 80)
    if isinstance(data.get("available"), bool) and facts.availability == "unknown":
        facts.availability = "in_stock" if data["available"] else "out_of_stock"


async def read_product(url: str, fetch: Fetcher) -> tuple[PageFacts | None, str]:
    """Fetch and parse one candidate. Returns (facts, reason) where reason explains a miss."""
    page = await fetch(url)
    if not page.ok or not page.final_url:
        return None, page.error or "fetch_failed"
    if page.content_type not in HTML_TYPES:
        return None, "not_html"
    final = page.final_url
    facts, canonical = parse_product_page(page.body, final)
    if canonical and host_of(canonical) == host_of(final):
        facts.url = canonical
    else:
        facts.url = final
    shopify = shopify_handle_url(final)
    if shopify and (facts.price_minor is None or facts.verification == "open_graph"):
        extra = await fetch(shopify)
        if extra.ok and extra.content_type in JSON_TYPES:
            try:
                data = json.loads(extra.body)
            except json.JSONDecodeError:
                data = None
            # Shopify JSON carries no currency; is_product still requires the page's INR.
            if isinstance(data, dict):
                apply_shopify(data, facts)
    if not facts.is_product:
        if facts.price_minor is not None and facts.currency not in (None, "INR"):
            return None, "not_inr"
        return None, "no_price" if facts.title else "not_a_product"
    return facts, "ok"


async def resolve_redirect(url: str, fetch: Fetcher) -> str | None:
    """Resolve a grounding redirect (or any link) to its final public URL."""
    page = await fetch(url)
    return page.final_url if page.ok else None


async def fetch_image(url: str) -> tuple[bytes, str] | None:
    """Download a public product image for composing a concept board."""
    result = await fetch_public(
        url,
        accept="image/webp,image/png,image/jpeg",
        allowed_types=IMAGE_TYPES,
        max_bytes=MAX_IMAGE_BYTES,
    )
    return (result.data, result.content_type) if result.ok and result.data else None
