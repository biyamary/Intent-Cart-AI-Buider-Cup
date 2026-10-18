# IntentCart UI review pack

These wireframes turn the October 2026 usability notes into a reviewable interface direction. They are intentionally higher fidelity than box diagrams, but they are not final visual specifications. Open each SVG directly in a browser; the canvas and text remain crisp at any zoom.

## Review files

- [Landing — desktop](./landing-desktop.svg)
- [Landing — mobile](./landing-mobile.svg)
- [Chat workspace — desktop](./workspace-desktop.svg)
- [Chat workspace — mobile](./workspace-mobile.svg)

## Core decisions

1. **People before features.** The landing page introduces **Nia — Food Guide** and **Mira — Personal Stylist** by name anywhere a chat starts. Neither specialist is the default or visually secondary.
2. **A message is the obvious first action.** Both hero actions use “Chat with…” language. Specialist cards repeat that action and supply a realistic starter prompt.
3. **The workspace fits the viewport.** A compact header replaces the oversized page introduction. On desktop, sessions stay on the left and work happens on the right. The message list scrolls inside the workspace; the composer stays visible.
4. **Progress without hidden reasoning.** The active turn displays plain-language stages such as “Planning your budget” and “Searching preferred stores,” plus elapsed time. It never reveals private chain-of-thought.
5. **Budget logic is inspectable.** The look panel shows an item range, the planned cap, reserved total, and redistribution after a change. A complete-basket check appears before results.
6. **Refinement is an ordinary action.** “Update this look” stays visible after results, with fast presets and free text. Selected pieces remain locked unless the user changes that choice.
7. **Mobile preserves focus.** Sessions move into a drawer and Chat/Look become explicit tabs. The composer remains attached to the bottom of the usable viewport.

## Annotated landing wireframe

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ Brand                        Food   Clothes                 My profile    │
├──────────────────────────────────────────────────────────────────────────┤
│ TWO SPECIALISTS. ONE EASIER CART.     ┌─ Nia / Food Guide ────────────┐ │
│ Ask. Decide.                          │ “Let's look at that label.”     │ │
│ Shop with confidence.                └─────────────────────────────────┘ │
│                                                                      [4] │
│ A short explanation names both         ┌─ Mira / Personal Stylist ─────┐ │
│ specialists and what they do. [1]      │ “I'll build the whole look.”  │ │
│                                        └────────────────────────────────┘ │
│ [ Chat with Nia / Food Guide ] [ Chat with Mira / Personal Stylist ] [2] │
│ Just describe what you need — they will guide the next step.          [3] │
├──────────────────────────────────────────────────────────────────────────┤
│ Meet your shopping specialists.                                           │
│ ┌─ Nia / Food Guide ─────────────┐  ┌─ Mira / Personal Stylist ────────┐ │
│ │ summary + capability chips     │  │ summary + capability chips       │ │
│ │ TRY ASKING: realistic prompt   │  │ TRY ASKING: realistic prompt     │ │
│ │ Chat with Nia                  │  │ Chat with Mira                    │ │
│ └────────────────────────────────┘  └──────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
```

- **[1] Orientation:** the first paragraph answers “who can I talk to?” before describing features.
- **[2] Equal entry points:** equal size, hierarchy, and proximity prevent food from reading as the only primary experience.
- **[3] Low-friction reassurance:** users do not need to understand commands or prepare structured input.
- **[4] Identity reinforcement:** initials, names, roles, and example dialogue make the cards feel like chat agents rather than generic tools.

## Annotated workspace wireframe

```text
┌────────────────────────────────────────────────────────────────────────────┐
│ ← Home   Mira · Personal Stylist                           Profile          │
├───────────────┬─────────────────────────────────────┬──────────────────────┤
│ SESSIONS      │ YOUR LOOK                         │ CHAT                  │
│ + New chat    │ Complete basket ✓                │ compact title     [2]│
│               │ Budget plan                       │                       │
│ ● Dinner look │ Shirt  ₹1,400                     │ You: smart-casual     │
│   Today       │ Pants  ₹1,500                     │ under ₹4,000          │
│ Interview     │ Shoes  ₹1,100                     │                       │
│ Weekend       │ Total  ₹4,000                 [4]│ Mira: progress card  │
│               │                                   │ ✓ Understanding      │
│               │ [ Update this look ]         [5]│ ● Planning · 8s  [3]│
│               │                                   │ ○ Searching stores   │
│               │                                   ├───────────────────────┤
│               │                                   │ Message Mira… [Send] │
│ [1]           │                                   │ Always visible    [6]│
└───────────────┴─────────────────────────────────────┴──────────────────────┘
```

- **[1] Sessions left:** history is available without pushing the active conversation below the fold.
- **[2] Compact context:** one line establishes agent and session; the large marketing title is removed.
- **[3] Safe progress:** stage labels and elapsed time prove that work continues without exposing hidden reasoning.
- **[4] Explainable allocation:** ranges and caps add up to the total and update immediately when an item changes.
- **[5] Fast refinement:** post-result changes are discoverable without restarting the conversation.
- **[6] Stable composer:** only the message region scrolls, so input and send stay in reach.

## Responsive behavior

| Width | Sessions | Chat and look | Composer |
| --- | --- | --- | --- |
| `> 1250px` | Persistent 252 px rail | Look board left, chat right | Pinned within chat column |
| `851–1250px` | Persistent 252 px rail | Chat/Look switch | Pinned within workspace |
| `≤ 850px` | Drawer opened from the top bar | One active tab at a time | Pinned within the usable viewport |

## Accessibility notes

- Agent cards are semantic articles with a single, explicit link instead of nested click targets.
- Focus states use the existing high-contrast lime outline and remain visible on every surface.
- Status changes should use `role="status"`/`aria-live="polite"`; error alerts should use `role="alert"` once per failed turn.
- Motion is decorative and disabled by the existing `prefers-reduced-motion` rule.
- Icon-only mobile actions require visible tooltips on pointer hover and descriptive accessible names.
