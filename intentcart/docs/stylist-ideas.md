# Stylist: next ideas

Ordered by value for effort. "Done" items shipped with the feedback / ideas-stage
work described in [shop-a-look.md](shop-a-look.md).

## Quick wins (days)

| Idea | Why | How |
| --- | --- | --- |
| **Image-aware ranking** | The ranker only reads titles; colour and embellishment are visual | Send each candidate's `image_url` to the ranker at `MEDIA_RESOLUTION_LOW` (cheap); score against the reference image and locked pieces |
| **Remember taste across chats** | Feedback dies with the look today | Summarise likes/dislikes into `Profile.style` (e.g. "prefers light jhumkas, avoids neon") and preload it, which `stylist_context` already does. ADK 2.11 adds a SQLite memory service; Vertex Memory Bank for Cloud Run |
| **Swipe mode on phones** | Feedback is the new superpower; make it one thumb | Full-screen card stack: swipe right = like, left = reason chips. Same `/feedback` endpoint |
| **Share the board for votes** | Indian occasion outfits are family decisions | Read-only share link plus 👍/👎 per card from guests, shown to the owner as "Mom liked this" |
| **Delivery-aware nudges** | An event in 3 days changes everything | When `event_date` is close, rank in-stock items first and proactively offer `find_local_boutiques` |
| **Curate the small-business registry** | `small_businesses.json` ships empty, so nothing earns the *verified* badge | Simple submission form (store URL, city, Instagram) and a manual review step that writes `source_url` + `reviewed_at` |

## Bigger bets (weeks)

| Idea | Why | How |
| --- | --- | --- |
| **"Find similar" from any image** | Users screenshot Instagram looks | `gemini-embedding-2` (multimodal) over a growing cache of verified products → nearest neighbours, then verify prices live |
| **Official store APIs** | Ajio / Nykaa block page checks; APIs give stable prices and affiliate revenue | Amazon Associates product API and Flipkart Affiliate API as extra nominators next to Google Search; same verification and labels |
| **Try it together** | People want to see the whole outfit | `visualize_look(kind="final")` already composes selected products. Add "on my photo" using the reference image with the image model, always labelled AI |
| **Price-drop / back-in-stock watch** | Weddings are planned weeks ahead | A scheduled job re-verifies saved looks' product pages and notifies on drops |
| **Wardrobe** | "I own this" is manual | Upload wardrobe photos once; `analyze_reference` tags them; checklist items auto-marked owned when a close match exists |
| **Local boutique catalogues** | Many small sellers live on Instagram/WhatsApp, which we cannot verify | Let boutiques upload a catalogue (photo + price) through a partner page; show as "listed by the boutique" |
| **Voice and Indian languages** | Hands-free, and many shoppers prefer Hindi, Malayalam or Tamil | Gemini Live (`gemini-3.8-live`) for voice; the stylist prompt already accepts Indian event names |
| **Rent or pre-loved** | Lehengas worn once are a natural rental | Add rental and resale stores as a retailer policy option with their own label |

## Gemini and ADK practices

Applied in this change:

- Pinned model IDs: `gemini-3.6-flash` for chat and search (3.5 Flash is deprecated), `gemini-3.5-flash-lite` for ranking (separate quota, cheaper). Verified live on the project.
- Thinking levels per job: `LOW` for search and ranking; the coordinator keeps the default (`medium`). Temperature is left at its default, as Google advises for Gemini 3.
- Per-image `media_resolution=HIGH` for reference photos, with the question placed after the media.
- Grounded search answers as Markdown link lists instead of JSON, because grounding sources are attached only to prose answers; plain store names instead of `site:` operators, which grounding drops.
- Already in place and kept: static prompt first and the live board snapshot last, so Vertex implicit context caching can reuse the prefix.

Worth adopting next:

- **ADK `require_confirmation`** (2.12) on `start_shopping`, so approval is enforced by the framework, not only by the prompt.
- **ADK evals** (`AgentEvaluator`, tool-trajectory metrics) for key flows: vague request → asks questions; reaction → `give_feedback`; never invents prices.
- **Event compaction** for long chats, and **`abort_signal`** (2.11) to cancel a superseded discovery run instead of letting it finish and be ignored.
- **URL context tool** (with Google Search) so the search agent can read a collection page and pick products itself. It is still `v1beta1` on Vertex, so it stays a candidate for now.
- **`gemini-3.8-flash`** for the coordinator if tool-use mistakes show up in evals; it is live on the project.
