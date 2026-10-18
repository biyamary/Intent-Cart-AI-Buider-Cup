"""Live product discovery as an ADK 2 dynamic workflow.

    look_discovery (Workflow)
      discover_look ── fan-out, one isolated sub-branch per checklist item ──┐
        discover_item                                                         │
          product_search_N  (LlmAgent + google_search; grounding captured)    │
          verify_candidates (function node: fetch + parse product pages)      │
          candidate_ranker  (LlmAgent, structured scores vs. locked pieces)   │
          -> writes the item's pool/progress to the look as soon as it ends ◄─┘

Search only nominates URLs. Prices, images, stock and ratings come from the
fetched pages (see pages.py); the shortlist and budget filter are deterministic
(see service.py). Jobs run in the background so a chat turn never waits on them.
"""

import asyncio
import json
import logging
from typing import Any
from uuid import uuid4

from google.adk import Context, Event, Workflow
from google.adk.agents.run_config import RunConfig
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import google_search
from google.adk.workflow import node
from google.genai import types

from app.agents.base import AgentDefinition, create_agent
from app.agents.privacy import adk_app
from app.agents.schemas import RankResult
from app.clothes.agent_calls import Source, collect_grounding, parse_json, urls_in
from app.clothes.pages import Fetcher, PageFacts, fetch_public, host_of, read_product
from app.clothes.sellers import (
    classify,
    is_store_url,
    popular_retailer_domains,
    small_business_domains,
)
from app.clothes.service import MIN_FIT, LookError, LookService, product_id
from app.config import Settings
from app.schemas import CatalogProduct, ChecklistItem, Look

logger = logging.getLogger(__name__)

MAX_URLS_PER_ITEM = 12
FETCH_CONCURRENCY = 6
# Items searched at once; keeps grounding requests under per-minute quotas.
SEARCH_CONCURRENCY = 3


MISS_LABELS = {
    "blocked_host": "unsafe address",
    "no_price": "no readable price",
    "not_a_product": "not a product page",
    "not_inr": "not priced in INR",
    "http_403": "blocked our check",
    "http_404": "page not found",
}


def miss_summary(misses: dict[str, int]) -> str:
    parts = [f"{count} {MISS_LABELS.get(reason, 'unreadable')}" for reason, count in misses.items()]
    return "(" + ", ".join(parts[:4]) + ")"


def rupees(minor: int) -> int:
    return minor // 100


def to_product(facts: PageFacts, category: str) -> CatalogProduct:
    label, note = classify(facts.url)
    return CatalogProduct(
        id=product_id(facts.url),
        category=category,
        title=facts.title[:200],
        price_minor=facts.price_minor or 0,
        retailer=facts.seller_name or host_of(facts.url),
        url=facts.url,
        image_url=facts.image_url,
        colour=facts.colour,
        source="live",
        price_fetched_at=facts.fetched_at,
        match_reason="",
        price_source="page",
        verification=facts.verification or "open_graph",
        availability=facts.availability,
        rating=facts.rating,
        rating_count=facts.rating_count,
        seller_label=label,
        seller_note=note,
    )


def brief_context(look: Look) -> dict:
    brief = look.brief
    analysis = look.analysis
    return {
        "occasion": brief.occasion,
        "description": brief.description,
        "event_date": brief.event_date,
        "sizes": brief.sizes,
        "colours": brief.colours,
        "avoid_colours": brief.avoid_colours,
        "platforms": brief.platforms,
        "country": "India",
        "palette": analysis.palette if analysis else [],
        "style_tags": analysis.style_tags if analysis else [],
    }


def locked_pieces(look: Look) -> list[dict]:
    return [
        {
            "category": i.category,
            "title": i.chosen_product.title,
            "colour": i.chosen_product.colour,
            "price_inr": rupees(i.chosen_product.price_minor),
        }
        for i in look.items
        if i.status == "locked" and i.chosen_product
    ]


class Discovery:
    def __init__(self, settings: Settings, looks: LookService, *, fetch: Fetcher = fetch_public):
        self.settings = settings
        self.looks = looks
        self.fetch = fetch
        self.search_model: Any = settings.gemini_model
        self.rank_model: Any = settings.gemini_lite_model
        self._tasks: set[asyncio.Task] = set()
        # (look_id, item_id) -> the newest search job; only it may write that item's results.
        self._owners: dict[tuple[str, str], str] = {}

    @property
    def enabled(self) -> bool:
        return self.settings.stylist_mode == "gemini" and self.settings.stylist_search_enabled

    # ------------------------------------------------------------------ public API
    async def start(
        self,
        uid: str,
        look_id: str,
        item_ids: list[str] | None = None,
        *,
        request: str = "",
        max_price_minor: int | None = None,
    ) -> list[str]:
        look = await self.looks.get(uid, look_id)
        targets = [
            i
            for i in look.items
            if i.status == "open"
            and (item_ids is None or i.id in item_ids)
            and (item_ids is not None or i.discovery != "searching")
        ]
        if not targets:
            return []
        if not self.enabled:
            for item in targets:
                await self.looks.apply_discovery(
                    uid, look_id, item.id, status="failed",
                    note="Live product search is not enabled on this server.",
                )
            return []
        for item in targets:
            await self.looks.apply_discovery(
                uid, look_id, item.id, status="searching", note="Searching stores…"
            )
        ids = [i.id for i in targets]
        job = uuid4().hex
        for item_id in ids:
            self._owners[(look_id, item_id)] = job
        self._spawn(self._run(
            uid, look_id, ids, "search", request, max_price_minor,
            job, look.plan_revision,
        ))
        return ids

    def owns(self, look_id: str, item_id: str, job: str | None) -> bool:
        return job is None or self._owners.get((look_id, item_id)) == job

    async def rescore(self, uid: str, look_id: str) -> None:
        """Re-rank open items against newly locked pieces, without searching again."""
        if not self.enabled:
            return
        look = await self.looks.get(uid, look_id)
        ids = [i.id for i in look.items if i.status == "open" and len(i.pool) > 1]
        if ids:
            self._spawn(self._run(
                uid, look_id, ids, "rank", "", None, None, look.plan_revision
            ))

    async def wait_idle(self) -> None:
        """Test/shutdown helper: wait for running jobs."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ------------------------------------------------------------------ job
    async def _run(
        self, uid, look_id, item_ids, mode, request, max_price_minor,
        job=None, plan_revision: int | None = None,
    ) -> None:
        try:
            async with asyncio.timeout(self.settings.discovery_timeout_seconds):
                look = await self.looks.get(uid, look_id)
                if plan_revision is not None and look.plan_revision != plan_revision:
                    return
                specs = [
                    self._spec(look, item, mode, request, max_price_minor)
                    for item in look.items
                    if item.id in item_ids and item.status == "open"
                ]
                if specs:
                    await self._execute(
                        self._workflow(uid, look_id, specs, job, plan_revision), uid
                    )
        except Exception as error:  # noqa: BLE001 -- background job; never log payloads
            logger.warning("Discovery job failed: mode=%s error_type=%s", mode, type(error).__name__)
        finally:
            if mode == "search":
                await self._fail_unfinished(
                    uid, look_id, item_ids, job, plan_revision
                )
                for item_id in item_ids:
                    if self._owners.get((look_id, item_id)) == job:
                        del self._owners[(look_id, item_id)]

    async def _fail_unfinished(
        self, uid, look_id, item_ids, job, plan_revision: int | None = None
    ) -> None:
        try:
            look = await self.looks.get(uid, look_id)
        except LookError:
            return
        for item in look.items:
            # A newer search for the same item owns it now; leave its progress alone.
            if not self.owns(look_id, item.id, job):
                continue
            if item.id in item_ids and item.discovery == "searching":
                await self.looks.apply_discovery(
                    uid, look_id, item.id, status="failed",
                    note="The search did not finish. Ask the stylist or press retry.",
                    expected_plan_revision=plan_revision,
                )

    def _spec(self, look: Look, item: ChecklistItem, mode, request, max_price_minor) -> dict:
        cap = item.budget_cap_minor
        if max_price_minor:
            cap = min(cap, max_price_minor)
        return {
            "item_id": item.id,
            "mode": mode,
            "category": item.category,
            "target": item.target,
            "hints": item.hints,
            "request": request,
            "cap_minor": cap,
            "search_cap_minor": (
                min(look.remaining_budget_minor, max_price_minor)
                if max_price_minor else
                look.remaining_budget_minor if mode == "search" and not item.pool else cap
            ),
            "max_price_minor": max_price_minor,
            "retailer_policy": look.brief.retailer_policy,
            "brief": brief_context(look),
            "locked": locked_pieces(look),
            "pool": [p.model_dump(mode="json") for p in item.pool] if mode == "rank" else [],
            "rejected": item.rejected_ids,
        }

    async def _execute(self, workflow: Workflow, uid: str) -> None:
        sessions = InMemorySessionService()
        app_name = "intentcart_discovery"
        runner = Runner(app=adk_app(app_name, workflow), session_service=sessions)
        session = await sessions.create_session(app_name=app_name, user_id=uid)
        try:
            async for _ in runner.run_async(
                user_id=uid,
                session_id=session.id,
                new_message=types.Content(role="user", parts=[types.Part(text="discover")]),
                run_config=RunConfig(max_llm_calls=4 * MAX_URLS_PER_ITEM),
            ):
                pass
        finally:
            await runner.close()

    # ------------------------------------------------------------------ workflow
    def _search_agent(self, index: int, sources: list[Source]):
        agent = create_agent(
            AgentDefinition(
                f"product_search_{index}",
                "Finds product pages for one outfit item with Google Search.",
                "stylist_search.md",
            ),
            model=self.search_model,
            tools=[google_search],
            conversational=True,
            # Grounding redirect URLs are long; leave room so the JSON is not truncated.
            max_output_tokens=16384,
            retry_attempts=4,
        )
        agent.after_model_callback = collect_grounding(sources)
        # Low thinking keeps the agent to a few targeted searches instead of dozens.
        agent.generate_content_config.thinking_config = types.ThinkingConfig(
            thinking_level=types.ThinkingLevel.LOW
        )
        return agent

    def _ranker(self):
        return create_agent(
            AgentDefinition("candidate_ranker", "Scores product candidates.", "stylist_rank.md"),
            model=self.rank_model,
            output_schema=RankResult,
            conversational=True,
            retry_attempts=4,
        )

    def _workflow(
        self,
        uid: str,
        look_id: str,
        specs: list[dict],
        job: str | None = None,
        plan_revision: int | None = None,
    ) -> Workflow:
        sources = {spec["item_id"]: [] for spec in specs}
        searchers = {
            spec["item_id"]: self._search_agent(n, sources[spec["item_id"]])
            for n, spec in enumerate(specs)
        }
        ranker = self._ranker()
        fetch, looks = self.fetch, self.looks
        semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)
        search_slots = asyncio.Semaphore(SEARCH_CONCURRENCY)

        async def verify_candidates(ctx: Context, node_input: dict) -> dict:
            """Fetch each nominated URL; keep only pages with verifiable INR prices."""

            async def one(url):
                async with semaphore:
                    return await read_product(url, fetch)

            results = await asyncio.gather(*(one(u) for u in node_input["urls"]))
            products, misses, seen = [], {}, set()
            for facts, reason in results:
                if facts is None:
                    misses[reason] = misses.get(reason, 0) + 1
                    continue
                if facts.url in seen or not is_store_url(facts.url):
                    continue
                seen.add(facts.url)
                products.append(to_product(facts, node_input["category"]).model_dump(mode="json"))
            return {"products": products, "checked": len(node_input["urls"]), "misses": misses}

        @node(rerun_on_resume=True)
        async def discover_item(ctx: Context, node_input: dict):
            spec, item_id = node_input, node_input["item_id"]
            try:
                found: dict = {}
                if spec["mode"] == "search":
                    async with search_slots:
                        found = await self._search(
                            ctx, spec, searchers[item_id], sources[item_id], verify_candidates
                        )
                    products, checked = found["products"], found["checked"]
                else:
                    products, checked = spec["pool"], 0
                products = [
                    p for p in products
                    if p["id"] not in spec["rejected"]
                    and (not spec["max_price_minor"] or p["price_minor"] <= spec["max_price_minor"])
                ]
                scores = await self._rank(ctx, ranker, spec, products) if products else {}
            except Exception as error:  # noqa: BLE001 -- one item failing must not stop siblings
                logger.warning("Discovery item failed: error_type=%s", type(error).__name__)
                if spec["mode"] == "search" and self.owns(look_id, item_id, job):
                    await looks.apply_discovery(
                        uid, look_id, item_id, status="failed",
                        note="Search for this item failed. Try again in a moment.",
                        expected_plan_revision=plan_revision,
                    )
                return {"item_id": item_id, "found": 0}

            if spec["mode"] == "rank":
                await looks.set_scores(
                    uid, look_id, item_id, scores,
                    expected_plan_revision=plan_revision,
                )
                return {"item_id": item_id, "found": len(products)}

            if not self.owns(look_id, item_id, job):
                return {"item_id": item_id, "found": 0, "superseded": True}
            pool = []
            for data in products:
                product = CatalogProduct.model_validate(data)
                if product.id in scores:
                    product.style_score, product.match_reason = scores[product.id]
                pool.append(product)
            pool.sort(key=lambda p: (-(p.style_score or 0), p.price_minor))
            fitting = [p for p in pool if p.style_score is None or p.style_score >= MIN_FIT]
            within = [p for p in fitting if p.price_minor <= spec["cap_minor"]]
            if within:
                status, note = "ready", f"Checked {checked} pages; {len(pool)} verified products."
            elif fitting:
                status = "no_results"
                note = (
                    f"Found {len(fitting)} matching products, but none within "
                    f"₹{rupees(spec['cap_minor']):,} for this item."
                )
            elif pool:
                status = "no_results"
                note = f"Found {len(pool)} products, but none matched this item well."
            else:
                status = "no_results"
                note = f"Checked {checked} pages; none showed a verifiable INR price."
                if misses := found.get("misses") if spec["mode"] == "search" else None:
                    note += " " + miss_summary(misses)
            await looks.apply_discovery(
                uid, look_id, item_id, status=status, pool=pool, note=note, replace=True,
                expected_plan_revision=plan_revision,
            )
            return {"item_id": item_id, "found": len(pool)}

        @node(rerun_on_resume=True)
        async def discover_look(ctx: Context, node_input):
            results = await asyncio.gather(
                *(ctx.run_node(discover_item, spec, use_sub_branch=True) for spec in specs)
            )
            yield Event(output={"items": list(results)})

        return Workflow(name="look_discovery", edges=[("START", discover_look)])

    async def _search(self, ctx, spec, searcher, sources, verify_candidates) -> dict:
        payload = {
            "item": {"category": spec["category"], "target": spec["target"], "hints": spec["hints"]},
            "latest_request": spec["request"],
            "brief": spec["brief"],
            "price_ceiling_inr": rupees(spec["search_cap_minor"]),
            "planned_item_budget_inr": rupees(spec["cap_minor"]),
            "retailer_policy": spec["retailer_policy"],
            "preferred_retailers": spec["brief"].get("platforms", []),
            "favour_domains": (
                small_business_domains()
                if spec["retailer_policy"] in {"independent_first", "independent_only"}
                else popular_retailer_domains()
            ),
        }
        text = await ctx.run_node(searcher, json.dumps(payload), use_sub_branch=True)
        data = parse_json(text)
        if isinstance(data, dict):
            nominated = [
                entry.get("url", "")
                for entry in data.get("products", [])
                if isinstance(entry, dict)
            ]
        else:
            # Malformed or truncated JSON: recover the URLs rather than lose the search.
            nominated = urls_in(text)
        # Grounding redirects are what the provider actually retrieved; model-written URLs
        # may be wrong, which the verifier will reveal.
        urls = list(dict.fromkeys(u for u in nominated + [s.uri for s in sources] if u))
        urls = urls[:MAX_URLS_PER_ITEM]
        if not urls:
            return {"products": [], "checked": 0}
        return await ctx.run_node(
            verify_candidates, {"urls": urls, "category": spec["category"]}
        )

    async def _rank(self, ctx, ranker, spec, products: list[dict]) -> dict[str, tuple[int, str]]:
        payload = {
            "brief": spec["brief"],
            "item": {"category": spec["category"], "target": spec["target"], "hints": spec["hints"]},
            "latest_request": spec["request"],
            "locked_pieces": spec["locked"],
            "candidates": [
                {
                    "id": p["id"],
                    "title": p["title"],
                    "price_inr": rupees(p["price_minor"]),
                    "seller": p["seller_label"],
                    "colour": p.get("colour", ""),
                }
                for p in products
            ],
        }
        result = parse_json(await ctx.run_node(ranker, json.dumps(payload), use_sub_branch=True))
        known = {p["id"] for p in products}
        scores = {}
        for entry in (result or {}).get("scores", []) if isinstance(result, dict) else []:
            if isinstance(entry, dict) and entry.get("id") in known:
                try:
                    score = max(0, min(100, int(entry.get("score", 0))))
                except (TypeError, ValueError):
                    continue
                scores[entry["id"]] = (score, str(entry.get("reason", ""))[:200])
        return scores
