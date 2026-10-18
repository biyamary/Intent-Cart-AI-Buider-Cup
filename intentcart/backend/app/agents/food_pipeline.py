"""Deterministic findings -> gap research -> citation checks/cache -> reporter."""

import asyncio
import logging
import re
from datetime import date
from itertools import zip_longest

from fastapi import HTTPException
from google.api_core.exceptions import GoogleAPICallError

from app.agents.food_agent import create_report_agent, create_research_agent
from app.agents.schemas import Explanation, ResearchResults
from app.memory.food_cache import FoodEvidenceCache
from app.schemas import RegulatoryAlert, now
from app.tools.food import build_report
from app.tools.food_evidence import verify_finding
from app.tools.food_fetch import COUNTRY_AUTHORITIES, allowed_url

logger = logging.getLogger(__name__)
RESEARCH_BATCH_SIZE = 3


def prioritized_gaps(report, home_country):
    """Give each additive a turn before common ingredients consume the budget."""
    groups = [[], []]
    for ingredient in report.ingredients:
        rows = sorted(
            (
                r
                for r in report.regulatory_alerts
                if r.ingredient == ingredient.canonical and not r.verified
            ),
            key=lambda r: r.country != home_country,
        )
        gaps = [
            {"ingredient": ingredient.canonical, "country": r.country, "kind": "regulation"}
            for r in rows
        ]
        if not ingredient.source_url:
            gaps.insert(
                1 if gaps else 0,
                {"ingredient": ingredient.canonical, "country": None, "kind": "purpose"},
            )
        groups[0 if ingredient.additive_id else 1].append(gaps)
    return [
        gap
        for group in groups
        for round_ in zip_longest(*group)
        for gap in round_
        if gap is not None
    ]


def research_failure(report, status):
    reason, message = {
        429: (
            "quota_or_capacity",
            "Live research is unavailable: Gemini reported a quota or capacity limit (429). Retry later; if it persists, check the API project's model quota and billing.",
        ),
        504: (
            "timeout",
            "Live research did not finish within the time limit. Completed findings have been kept; remaining evidence is unverified.",
        ),
    }.get(
        status,
        (
            "provider_failure",
            "Live research is unavailable because the research service could not complete the request. Completed findings have been kept; retry later.",
        ),
    )
    report.research.failure_reason = reason
    report.research.message = message
    logger.warning("Food research stopped: status=%s reason=%s", status, reason)


def acceptable_prose(text: str) -> bool:
    # Defense in depth; prompts remain responsible for grounded phrasing.
    return not re.search(
        r"\bsafe\b|\bsafely\b|\bharmless\b|\brisk[- ]free\b|\bcauses? cancer\b|https?://|www\.",
        text,
        re.IGNORECASE,
    )


def report_sources(report) -> set[str]:
    candidates = [a.source_url for a in report.regulatory_alerts if a.verified]
    for ingredient in report.ingredients:
        candidates.extend(
            [ingredient.source_url, ingredient.iarc.source_url if ingredient.iarc else None]
        )
    sources = set()
    for url in candidates:
        if url:
            try:
                allowed_url(url)
                sources.add(url)
            except ValueError:
                pass
    return sources


class FoodPipeline:
    def __init__(self, settings, store, runtime):
        self.settings, self.runtime = settings, runtime
        self.cache = FoodEvidenceCache(store, settings.food_cache_days)
        # Coalesce concurrent misses in this worker; Firestore shares completed results
        # across workers. Cross-worker research can race without a distributed lease.
        self.research_lock = asyncio.Lock()

    async def analyze(self, scan, confirmed, profile, uid):
        report = build_report(scan, confirmed, profile)
        coverage = report.research
        async with self.research_lock:
            gaps = prioritized_gaps(report, profile.country)
            coverage.total_gaps = len(gaps)
            missing = []
            for gap in gaps:
                try:
                    cached = await self.cache.get(**gap)
                except (GoogleAPICallError, OSError, TimeoutError):
                    cached = None  # Cache availability must not erase deterministic findings.
                if cached:
                    self.apply(report, cached)
                    coverage.cache_hits += 1
                else:
                    missing.append(gap)
            if (
                missing
                and self.settings.agent_mode == "gemini"
                and self.settings.food_research_enabled
            ):
                requested = [
                    g
                    for g in missing
                    if g["country"] is None or g["country"] in COUNTRY_AUTHORITIES
                ][: self.settings.food_research_max_gaps]
                try:
                    # One total deadline, with smaller requests and results saved between batches.
                    async with asyncio.timeout(self.settings.agent_timeout_seconds):
                        for start in range(0, len(requested), RESEARCH_BATCH_SIZE):
                            batch = requested[start : start + RESEARCH_BATCH_SIZE]
                            coverage.attempted += len(batch)
                            await self.research_batch(report, batch, uid)
                except HTTPException as error:
                    research_failure(report, error.status_code)
                except TimeoutError:
                    research_failure(report, 504)
                coverage.status = (
                    "unavailable"
                    if coverage.failure_reason and not coverage.verified
                    else "partial"
                    if coverage.verified < len(missing)
                    else "completed"
                )
            elif missing:
                coverage.status = "disabled"
                coverage.message = "Live research is disabled. Only the ingredient database and previously verified evidence were used."
            coverage.deferred = len(missing) - coverage.attempted
            if not coverage.message and missing:
                coverage.message = (
                    f"Research verified {coverage.verified} of {coverage.attempted} requested evidence gaps. "
                    f"{coverage.deferred} gaps were not researched within this review's limits or supported sources."
                )
            if coverage.message:
                report.things_to_watch.append(coverage.message)
        unresolved = sum(not row.verified for row in report.regulatory_alerts)
        total = len(report.regulatory_alerts)
        report.summary += f" Evidence is available for {total - unresolved} of {total} ingredient-country comparisons; {unresolved} remain unverified."
        if coverage.failure_reason:
            report.summary += " Live research could not be completed."
        if (
            self.settings.agent_mode == "gemini"
            and not coverage.failure_reason
            and total > unresolved
        ):
            try:
                explanation = await self.runtime.run(
                    create_report_agent(self.settings),
                    uid,
                    {"report": report.model_dump(mode="json")},
                    Explanation,
                )
                if explanation.summary.strip() and acceptable_prose(explanation.summary):
                    report.summary += " " + explanation.summary
            except HTTPException:
                pass  # Preserve the usable deterministic report if generation fails.
        return report

    async def research_batch(self, report, batch, uid):
        results = await self.runtime.run(
            create_research_agent(self.settings),
            uid,
            {"gaps": batch, "as_of": date.today().isoformat()},
            ResearchResults,
        )
        keys = {(g["ingredient"], g["country"], g["kind"]) for g in batch}
        grouped = {}
        for finding in results.findings:
            key = (finding.ingredient, finding.country, finding.kind)
            if key in keys:
                grouped.setdefault(key, []).append(finding)

        # Do not promote contradictory duplicates. Verify each citation independently.
        async def verify_and_save(candidate):
            checked = await verify_finding(candidate)
            if checked:
                checked["checked_at"] = now()
                self.apply(report, checked)
                report.research.verified += 1
                try:
                    await self.cache.put(checked)
                except (GoogleAPICallError, OSError, TimeoutError):
                    report.things_to_watch.append(
                        "Verified evidence could not be cached; a later request may repeat research."
                    )

        # Each task applies its result immediately, so a later timeout cannot erase it.
        await asyncio.gather(
            *(verify_and_save(items[0]) for items in grouped.values() if len(items) == 1)
        )

    @staticmethod
    def apply(report, finding):
        if finding["kind"] == "purpose":
            for ingredient in report.ingredients:
                if ingredient.canonical == finding["ingredient"]:
                    ingredient.role = finding["purpose"]
                    ingredient.explanation = (
                        "Citation matched; technological purpose requires review: "
                        + finding["quote_or_snippet"]
                    )
                    ingredient.source_url = finding["url"]
                    ingredient.purpose_basis = "citation_verified"
            return
        for index, row in enumerate(report.regulatory_alerts):
            if (row.ingredient, row.country) == (finding["ingredient"], finding["country"]):
                report.regulatory_alerts[index] = RegulatoryAlert(
                    ingredient=row.ingredient,
                    country=row.country,
                    status=finding["status"],
                    condition=finding["condition"],
                    source_url=finding["url"],
                    verified=True,
                    verification="citation_verified",
                    quote_or_snippet=finding["quote_or_snippet"],
                    checked_at=finding["checked_at"],
                    effective_from=finding.get("effective_from"),
                    review_after=finding.get("review_after"),
                )
