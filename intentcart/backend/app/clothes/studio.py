"""Specialist capabilities the stylist coordinator calls through its tools.

- analyze_reference: multimodal structured analysis of a reference image/description
- find_inspiration: Pinterest pins + editorial pages via Google Search
- generate_concept: Gemini image model concept boards (always labelled as AI concepts)
- find_boutiques: Google Maps grounded local shops
- styling_note: final note for an assembled look
"""

import asyncio
import json
import re
from typing import Any

from google.adk.tools import google_search
from google.adk.tools.google_maps_grounding_tool import google_maps_grounding
from google.genai import types

from app.agents.base import AgentDefinition, create_agent
from app.agents.google_client import create_genai_client
from app.agents.schemas import Explanation
from app.clothes.agent_calls import parse_json, run_once
from app.clothes.pages import Fetcher, fetch_public, host_of, normalise_url, parse_product_page
from app.config import Settings
from app.schemas import Boutique, InspirationItem, Look, LookAnalysis

PIN_RE = re.compile(r"^https://(?:[a-z]{2,3}\.)?pinterest\.[a-z.]{2,6}/pin/([\w-]{3,40})/?", re.IGNORECASE)


class StudioError(Exception):
    """A capability failed or is unavailable; message is safe to show."""


def pin_url(url: str) -> str | None:
    match = PIN_RE.match(url or "")
    return f"https://www.pinterest.com/pin/{match.group(1)}/" if match else None


class Studio:
    def __init__(self, settings: Settings, *, fetch: Fetcher = fetch_public):
        self.settings = settings
        self.fetch = fetch
        self.models: dict[str, Any] = {}  # tests may override per capability

    def _model(self, key: str, lite: bool = False):
        default = self.settings.gemini_lite_model if lite else self.settings.gemini_model
        return self.models.get(key, default)

    def _agent(self, name: str, prompt: str, *, tools=None, schema=None, lite=False):
        return create_agent(
            AgentDefinition(name, f"Shop a Look {name}", prompt),
            model=self._model(name, lite),
            tools=tools or [],
            output_schema=schema,
            conversational=True,
            retry_attempts=3,
        )

    # ------------------------------------------------------------------ analysis
    async def analyze_reference(
        self, request: str, images: list[tuple[bytes, str]], look: Look | None
    ) -> LookAnalysis:
        agent = self._agent("reference_analysis", "stylist_analyze.md", schema=LookAnalysis)
        payload = {
            "request": request,
            "occasion": look.brief.occasion if look else "",
            "description": look.brief.description if look else "",
        }
        parts = [types.Part.from_text(text=json.dumps(payload))]
        parts += [types.Part.from_bytes(data=data, mime_type=mime) for data, mime in images]
        result = await run_once(agent, parts, timeout=60, max_llm_calls=2)
        data = parse_json(result.text)
        if not isinstance(data, dict):
            raise StudioError("The reference could not be analysed. Try describing it instead.")
        return LookAnalysis.model_validate(data)

    # ------------------------------------------------------------------ inspiration
    async def find_inspiration(self, look: Look, request: str) -> list[InspirationItem]:
        if not self.settings.stylist_search_enabled:
            raise StudioError("Inspiration search needs Google Search, which is disabled.")
        agent = self._agent("inspiration_search", "stylist_inspiration.md", tools=[google_search])
        payload = {
            "occasion": look.brief.occasion,
            "description": look.brief.description,
            "palette": look.analysis.palette if look.analysis else look.brief.colours,
            "style_tags": look.analysis.style_tags if look.analysis else [],
            "pieces": [i.target or i.category for i in look.items if i.status != "removed"],
            "request": request,
        }
        result = await run_once(agent, [types.Part.from_text(text=json.dumps(payload))], timeout=60)
        data = parse_json(result.text) or {}
        pins, pages = [], []
        for entry in data.get("pins", []) if isinstance(data, dict) else []:
            if isinstance(entry, dict) and (url := pin_url(entry.get("url", ""))):
                pins.append((url, str(entry.get("title", ""))[:160]))
        for entry in data.get("pages", []) if isinstance(data, dict) else []:
            url = normalise_url(entry.get("url", "")) if isinstance(entry, dict) else None
            if url and not pin_url(url):
                pages.append((url, str(entry.get("title", ""))[:160]))
        # Grounded results are real; model-written pin URLs are checked by the widget.
        for source in result.sources:
            page = await self.fetch(source.uri) if len(pins) < 6 else None
            if page and page.ok and page.final_url and (url := pin_url(page.final_url)):
                pins.append((url, source.title[:160]))

        items, seen = [], set()
        for url, title in pins:
            if url not in seen and len(items) < 6:
                seen.add(url)
                items.append(InspirationItem(kind="pinterest", url=url, title=title, source="Pinterest"))
        previews = await asyncio.gather(*(self._preview(url) for url, _ in pages[:4]))
        for (url, title), preview in zip(pages[:4], previews):
            if preview and preview[1] and url not in seen:
                seen.add(url)
                items.append(
                    InspirationItem(
                        kind="web", url=preview[0], title=preview[2] or title,
                        image_url=preview[1], source=preview[3],
                    )
                )
        return items

    async def _preview(self, url: str):
        page = await self.fetch(url)
        if not page.ok or not page.final_url or not page.body:
            return None
        facts, _ = parse_product_page(page.body, page.final_url)
        return page.final_url, facts.image_url, facts.title, facts.seller_name or host_of(page.final_url)

    # ------------------------------------------------------------------ images
    async def generate_concept(self, prompt: str, images: list[tuple[bytes, str]]) -> tuple[bytes, str]:
        if not self.settings.stylist_images_enabled:
            raise StudioError("Concept images are disabled on this server.")
        client = create_genai_client(self.settings)
        parts = [types.Part.from_bytes(data=d, mime_type=m) for d, m in images[:6]]
        parts.append(types.Part.from_text(text=prompt))
        try:
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=self.settings.gemini_image_model,
                    contents=[types.Content(role="user", parts=parts)],
                    config=types.GenerateContentConfig(
                        response_modalities=["IMAGE", "TEXT"],
                        image_config=types.ImageConfig(aspect_ratio="3:4"),
                    ),
                ),
                timeout=90,
            )
        except Exception as error:
            raise StudioError("The concept image could not be generated right now.") from error
        for candidate in response.candidates or []:
            for part in (candidate.content.parts if candidate.content else None) or []:
                if part.inline_data and part.inline_data.data:
                    return part.inline_data.data, part.inline_data.mime_type or "image/png"
        raise StudioError("The image model returned no image. Try rephrasing the idea.")

    # ------------------------------------------------------------------ boutiques
    async def find_boutiques(self, look: Look, category: str, target: str) -> list[Boutique]:
        if not self.settings.stylist_maps_enabled:
            raise StudioError("Local boutique search (Google Maps) is not enabled on this server.")
        place = look.brief.delivery_city or look.brief.delivery_pin
        if not place:
            raise StudioError("Ask the user for their city or PIN code first.")
        agent = self._agent("boutique_search", "stylist_boutiques.md", tools=[google_maps_grounding])
        payload = {"item": {"category": category, "target": target}, "location": place,
                   "event_date": look.brief.event_date}
        result = await run_once(agent, [types.Part.from_text(text=json.dumps(payload))], timeout=60)
        data = parse_json(result.text) or {}
        maps_urls = {s.title.lower(): s.uri for s in result.sources if s.kind == "maps" and s.title}
        boutiques = []
        for entry in data.get("boutiques", []) if isinstance(data, dict) else []:
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            name = str(entry["name"])[:120]
            # Prefer the Maps URI from grounding; a model-written URL is used only if it is Maps.
            url = maps_urls.get(name.lower())
            written = normalise_url(str(entry.get("maps_url", "")))
            if not url and written and re.match(r"https://(maps\.google\.|www\.google\.[a-z.]+/maps|maps\.app\.goo\.gl)", written):
                url = written
            note = " · ".join(x for x in [str(entry.get("area", ""))[:80], str(entry.get("why", ""))[:160]] if x)
            boutiques.append(Boutique(name=name, url=url, note=note, kind="local"))
        return boutiques[:5]

    # ------------------------------------------------------------------ note
    async def styling_note(self, look: Look) -> str:
        agent = self._agent("styling_note", "stylist_note.md", schema=Explanation, lite=True)
        payload = {
            "occasion": look.brief.occasion,
            "brief": look.brief.description,
            "selected": [
                {"category": i.category, "title": i.chosen_product.title,
                 "colour": i.chosen_product.colour}
                for i in look.items if i.status == "locked" and i.chosen_product
            ],
            "owned": [i.category for i in look.items if i.status == "owned"],
            "removed": [i.category for i in look.items if i.status == "removed"],
        }
        result = await run_once(agent, [types.Part.from_text(text=json.dumps(payload))], timeout=45)
        data = parse_json(result.text)
        return Explanation.model_validate(data).summary if isinstance(data, dict) else ""


def concept_prompt(kind: str, look: Look, instructions: str) -> str:
    # The user's direction comes first and wins over the stored brief/checklist.
    direction = (
        f"The user's direction, which overrides anything below: {instructions}\n"
        if instructions.strip()
        else ""
    )
    base = (
        "Create a clean, photographic fashion flat-lay on a soft neutral background. "
        "Show only clothing and accessories; no people, faces, text, logos or watermarks.\n"
    )
    if kind == "edit_reference":
        return direction + (
            "Edit the attached reference outfit image to apply that direction, keeping the "
            "garments, colours and composition otherwise the same. Remove any person: show the "
            "garments and accessories as a styled flat-lay. No text, logos or watermarks."
        )
    if kind == "final":
        return direction + base + (
            "Arrange exactly the products shown in the attached product photos together as one "
            f"coordinated look for a {look.brief.occasion}. Keep their colours and designs faithful."
        )
    pieces = "; ".join(i.target or i.category for i in look.items if i.status != "removed")
    palette = ", ".join((look.analysis.palette if look.analysis else []) or look.brief.colours)
    return direction + base + (
        f"Concept for a {look.brief.occasion} look. Pieces: {pieces or look.brief.description}. "
        f"Palette: {palette or 'as suits the occasion'}."
    )
