# Food agent

The food agent offers two complementary paths:
1. **Conversational Food Companion (`/agents/food/sessions`)**: An interactive chatbot path that greets the user, gathers and confirms their ingredients list, checks for allergies, dietary restrictions, and target age groups, asks which country regulations (e.g. US, EU, UK, India) should be reviewed, demystifies chemical additive terms and E-numbers, performs grounded Google Search and official evidence fetch, and highlights "good" vs "bad"/watch-out components.
2. **Deterministic Scan & Report Pipeline (`/api/food/scans/{id}/analyze`)**: Runs structured batch gap-research, citation checks, and caching on extracted labels. `/ask` answers from the saved report.

## Enable

In `backend/.env`, set `FOOD_AGENT_MODE=gemini` to enable the Food Companion chat
independently, or `AGENT_MODE=gemini` to enable all agents. Configure either
[Vertex AI and local ADC](vertex-ai.md) (`GOOGLE_GENAI_USE_VERTEXAI=true`) or a
server-side `GOOGLE_API_KEY` for the Gemini Developer API.
Restart the backend after editing `.env`, then refresh the frontend. Uvicorn's
default `--reload` does not watch `.env` changes. `/api/agents` must report
`"enabled": true` for `food` before chat messages can be sent.
`FOOD_RESEARCH_ENABLED=true` enables gap research with ADK's Gemini Google Search
grounding API. This is the built-in `google_search`, not a Custom Search JSON API
integration; a separate search engine ID is not needed. The configured Gemini
model/project must support search grounding. The search agent has only that tool
and is exposed to the researcher using `AgentTool`. The research agent also has
the custom `fetch_food_evidence` function tool. The reporter has `output_schema`
and no tools. Research returns JSON validated by Pydantic without combining
function tools and an output schema in its model request.

`AGENT_MODE=demo` performs local database/profile checks without model or web calls.
Conversational chat is disabled in demo mode unless `FOOD_AGENT_MODE=gemini`
overrides it; the scanner's typed ingredient review remains available in demo mode.
Set `STORE_BACKEND=firestore`, `GOOGLE_CLOUD_PROJECT`, and Application Default
Credentials for durable shared caching (`uv sync --extra cloud`). Memory mode
caches within the process. Existing Firestore rules deny direct client access;
the Admin SDK writes the server-owned `food_evidence` collection. The cache never
contains user IDs, allergies, ages, diets, labels or profile data. It contains only
canonical ingredient/country findings and public source evidence.

## Evidence and limits

- `app/data/ingredients.json` owns names, E/INS aliases, purposes and deterministic
  IARC tags. Unknown classifications remain absent, never implicitly Group 3.
- Normalization preserves E/INS subtypes such as `503(ii)`, nested round/square
  brackets and single annotations such as `(maida)` or `(from soyabean)`. Percentages
  do not become ingredients. Functional classes from the label are marked `label`,
  distinct from reviewed purposes and citation-matched research. Added purpose
  entries cover sugar, lecithins, ammonium bicarbonate and propylene glycol; this
  is still a small curated database, not a comprehensive ingredient dictionary.
- `app/data/regulations.json` owns reviewed scoped rules, source URLs, review dates
  and recheck deadlines. Seeds were checked on **2026-10-18**. The EU titanium
  dioxide withdrawal is linked to Regulation 2022/63 and corroborated by the FSA
  COT document because EUR-Lex blocked automated retrieval. UK findings preserve
  Great Britain/Northern Ireland divergence. Red 3 is a US transition until the
  food deadline; the row expires for re-research on 2027-01-15. BVO is separately
  marked withdrawn after its compliance period. US rows describe federal scope.
  The propylene glycol US row links to 21 CFR 184.1666 and preserves food-category
  concentration limits rather than asserting product compliance.
- The fetch allowlist is hard-coded in `app/tools/food_fetch.py`. Only HTTPS on
  these domains or their subdomains is accepted. Credentials, nonstandard ports,
  private/non-global DNS answers and off-list redirects are rejected. Connections
  use the checked public IP while retaining TLS hostname validation. Environment
  proxies are not used. Responses are capped at 2 MB and 24,000 text characters.
  HTML/plain text are supported; PDF, compressed, inaccessible and oversized
  responses fail closed. Reviewed PDF seed citations remain available to humans.
- Web/search text is untrusted evidence. The verifier independently fetches the
  source, checks its jurisdiction, matches a known ingredient alias or E/INS code
  in an exact passage, and requires that passage to occur in the page. This checks
  **citation integrity, not semantic entailment or legal compliance**. The UI
  distinguishes `reviewed` from `citation_verified` results. Research never writes
  IARC tags or overrides reviewed database findings.
- Only verified research is cached, by canonical ingredient, country and evidence
  kind. `FOOD_CACHE_DAYS` defaults to 30 (maximum 90); a supplied recheck deadline
  shortens it. Cache misses are serialized within a worker. Different workers may
  concurrently research the same first miss; a distributed lease is not implemented.
- `FOOD_RESEARCH_MAX_GAPS` defaults to 12. Additives receive research priority,
  taking turns across ingredients with the profile's country first (if selected).
  Missing purposes share this budget. Research uses batches of at most three gaps;
  verified results are applied and cached as they complete. `AGENT_TIMEOUT_SECONDS`
  bounds the whole research phase, and `AGENT_MAX_LLM_CALLS` bounds each batch.
  Remaining gaps, failed quotes, conflicting
  duplicate answers and research outages remain `unverified`. No failed findings
  enter the shared cache. Oversized pages are not assumed to lack an ingredient.
- Reports include research counts (requested, verified, deferred, cache hits) and
  an explicit failure category. A 429 stops further research and reporter calls for
  that review. The deterministic coverage summary remains visible; missing evidence
  is not described as successfully checked. Fully unresolved reports skip the model
  reporter. The UI allows editing/re-running a saved label without uploading again.
- Default countries are EU, UK, India and US, plus the profile country. A profile's
  `food_countries` or explicit confirmation selection overrides this set. Canada,
  Australia/NZ and Japan can be selected. Japan and legacy UAE currently have no
  national authority in the approved list and remain unverified.
- Diet/allergen rules are incomplete label matches. Age advisories preserve scope:
  the glycerol example applies to UK slush ice drinks and specified child ages,
  not all foods containing glycerol. Missing quantities, exact age and product
  category prevent individual suitability or compliance conclusions.
  An empty allergies/diet profile means no personal matching was performed. Label
  allergen matches are displayed independently, including `maida` and `soyabean`.
- Reporter and QA prompts use only supplied evidence. A code guard rejects
  generated suitability assurances and prose URLs; QA source arrays are restricted
  to saved report sources. This is defense in depth, not a proof that generated
  prose cannot hallucinate. Reports remain usable when research/report generation
  fails. Re-analyze after profile changes.

## Validation

Run `uv run pytest` in `backend` and `npm run build` in `frontend`.
`tests/test_food_agent.py` exercises network boundaries, redirect policy, DNS
pinning, quote verification, expiry, normalization, IARC context, matrix scope,
ADK tool isolation, profile checks, cache reuse and failure fallback without live
API calls. Live Gemini, external source availability and Firestore credentials
must also be checked in the deployment environment.

If a report shows a quota/capacity failure, resolve the Gemini project's quota or
billing restriction (or retry after a temporary capacity limit clears), then use
**Edit ingredients & run review again**. Saved reports do not update automatically.
