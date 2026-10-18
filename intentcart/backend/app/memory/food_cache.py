import hashlib
import json
from datetime import UTC, datetime, timedelta

from app.agents.schemas import ResearchFinding
from app.tools.food_fetch import allowed_url, authority_url

CACHE_VERSION = 1


def evidence_key(ingredient: str, country: str | None, kind: str) -> str:
    value = json.dumps([CACHE_VERSION, ingredient, country, kind], ensure_ascii=True)
    return hashlib.sha256(value.encode()).hexdigest()


class FoodEvidenceCache:
    """Shared, server-owned public evidence only; no profile or user identifiers."""

    def __init__(self, store, days: int):
        self.store, self.days = store, days

    async def get(self, ingredient, country, kind):
        try:
            entry = await self.store.get_evidence(evidence_key(ingredient, country, kind))
            if not entry or entry.get("version") != CACHE_VERSION or not entry.get("verified"):
                return None
            if datetime.fromisoformat(entry["expires_at"]) <= datetime.now(UTC):
                return None
            finding = ResearchFinding.model_validate(entry["finding"])
            if (finding.ingredient, finding.country, finding.kind) != (ingredient, country, kind):
                return None
            allowed_url(finding.url)
            if kind == "regulation" and (
                finding.status == "unverified" or not authority_url(finding.url, country)
            ):
                return None
            return finding.model_dump() | {"checked_at": entry["checked_at"], "verified": True}
        except (ValueError, KeyError, TypeError):
            return None

    async def put(self, verified: dict):
        if not verified.get("verified"):
            return
        finding = ResearchFinding.model_validate(
            {k: v for k, v in verified.items() if k in ResearchFinding.model_fields}
        )
        now = datetime.now(UTC)
        expires = now + timedelta(days=self.days)
        if finding.review_after:
            expires = min(expires, datetime.fromisoformat(finding.review_after).replace(tzinfo=UTC))
        await self.store.put_evidence(
            evidence_key(finding.ingredient, finding.country, finding.kind),
            {
                "version": CACHE_VERSION,
                "verified": True,
                "checked_at": now.isoformat(),
                "expires_at": expires.isoformat(),
                "finding": finding.model_dump(),
            },
        )
