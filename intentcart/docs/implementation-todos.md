# Next implementation steps

The scaffold intentionally stops short of production agent behavior. Implement these seams in order:

1. **Prompts and evaluations.** Replace the five `TODO_PROMPT` files; pin Gemini IDs supported by your project. Add grounded-output, hallucination, prompt-injection, citation, uncertainty and food suitability evaluations. The runtime rejects untouched placeholders before making a network call.
2. **Food data.** Review the allergen dictionary; handle negations, derivative ambiguity and multilingual labels. Implement canonical ingredient/additive normalization. Add reviewed regulation entries with source dates and conditions; add source-backed diet/age checks. Do not interpret empty result lists as a clean bill of health.
3. **Food integrations.** Test Open Food Facts unknown barcodes, rate limits, attribution and licensing. Exercise real label OCR on poor images. Add retries only where an operation is safe to repeat. Validate decoded image content in addition to MIME and size. Add limits at the proxy for oversized multipart requests.
4. **Stylist discovery.** Expand the 14 fixtures to a reviewed catalog if desired. Implement `grounded_product_search` with a separate search-enabled ADK agent; validate returned URLs/prices and show retrieval timestamps. Add style ranking anchored to locked items and profile preferences. Add a reference-image input and validation path. `ParsedBrief.missing_information` needs a user clarification UI before richer brief parsing is enabled.
5. **Auth and persistence.** Configure and test Firebase, authorized origins, token expiry/revocation, Firestore IAM and deployment secrets. Add transaction / revision checks to protect look updates across tabs or instances. Consider deletion/export and retention requirements for real user data.
6. **Progress and memory.** Add an SSE event contract for meaningful stages and cancellation, then persistent ADK sessions if follow-ups need chat history. The current request/response API supplies all context explicitly.
7. **Device and deployment checks.** Test camera permissions, PWA icons/installability on target devices, Cloud Run startup, SPA routing, signed-in use and cold starts. A Dockerfile is provided; no infrastructure has been provisioned.

Out of scope for this scaffold: purchases, checkout, price tracking, unsupported product categories, live delivery promises, a pitch deck or contest submission.
