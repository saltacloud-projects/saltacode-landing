---
name: accessibility-quality
description: "Trigger: accessibility, a11y, semantics, keyboard, screen reader, focus. Protect inclusive critical paths beyond automated scores."
license: Apache-2.0
metadata:
  author: "Oscar Vargas"
  version: "1.0.0"
---

## Activation Contract

Load this skill for UI, navigation, content hierarchy, forms, motion, color, media, dialogs, or chat behavior.

## Hard Rules

- Use native semantics before ARIA; never use ARIA to hide broken interaction.
- Preserve keyboard access, visible focus, logical order, and reduced-motion behavior.
- Do not declare accessibility from an automated score alone.
- Keep validation and error messaging perceivable without relying only on color.

## Decision Gates

| Surface | Required checks |
|---|---|
| Navigation | Landmarks, skip link, keyboard order, mobile menu focus. |
| Content/media | Heading order, language, alternatives, contrast, zoom. |
| Form/chat | Labels, errors, status announcements, focus return, escape behavior. |
| Animation | Reduced motion and no essential motion-only meaning. |

## Execution Steps

1. Identify critical paths and semantic structure.
2. Run automated checks on representative routes.
3. Complete keyboard-only checks at desktop and mobile widths.
4. Test critical paths with a screen reader and browser zoom.
5. Record failures with element, impact, reproduction, and acceptance evidence.

## Output Contract

Return tested environment, automated results, manual keyboard/screen-reader evidence, prioritized failures, and unresolved limitations.

## References

- `../../../docs/quality/seo-performance-contract.md`
- `../../../docs/architecture/ai-chat-boundary.md`
