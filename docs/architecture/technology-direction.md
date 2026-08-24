# Technology direction: static-first Astro

Adopt Astro with TypeScript and pnpm, generate static-first output, and host the built site on Cloudflare Pages. Use islands only where interaction requires client JavaScript. This is a direction for a separate migration phase, not an implementation in the agentic foundation.

## Decision

| Concern | Direction |
|---|---|
| Rendering | Pre-render indexable marketing content to HTML. |
| Language | TypeScript for build-time and interactive code. |
| Package manager | pnpm with a committed lockfile. |
| Hosting | Cloudflare Pages with preview deployments and explicit production promotion. |
| Interactivity | Astro islands with the smallest possible client directives. |
| AI chat | Lazy client shell calling an edge/backend boundary; the external agent remains outside this repository. |
| Content | Semantic HTML first; introduce a content collection or CMS only for a proven publishing workflow. |

## Why this fits

- The current product is predominantly static marketing content.
- Pre-rendering keeps primary copy available without JavaScript and minimizes hydration cost.
- Componentization improves consistency without requiring a browser-heavy application runtime.
- Cloudflare Pages can serve static output globally while an edge function protects the AI integration boundary.

## Alternatives and tradeoffs

### Retain plain static HTML

This has the lowest runtime complexity and can perform extremely well. It remains viable for a small, rarely changed page, but the current monolithic file, copied vendor tree, and lack of an asset pipeline make systematic SEO, content, and component changes harder to validate.

### Next.js

Next.js is appropriate when the site needs substantial server rendering, authenticated application routes, or a unified full-stack React product. For this landing page it introduces more runtime and framework surface than current requirements justify. It remains an option if the product boundary expands materially.

### Full client-side SPA

A SPA can support complex application state, but it adds hydration and JavaScript to content that should be immediately indexable. It creates unnecessary SEO and Core Web Vitals risk for this use case and is not recommended as the default shell.

## Migration constraints

1. Capture the live URL, redirect, metadata, structured-data, and performance baseline first.
2. Preserve existing public URLs and canonical intent or provide tested permanent redirects.
3. Migrate content and semantics before redesigning visual behavior.
4. Keep chat and non-critical widgets outside the initial rendering path.
5. Compare preview and production evidence before promotion.

Framework migration, asset conversion, design changes, DNS changes, and deployment are separate, explicitly approved phases.
