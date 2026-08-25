# Image asset contract

This contract covers Saltacode brand images and the client logos currently rendered by the landing page. About and service photography are intentionally outside this pass.

## Surface variants

- `onLight` is the variant for a light surface.
- `onDark` is the variant for a dark surface.
- The pre-paint theme bootstrap selects the correct variant for light, dark, or system mode before themed images load.
- Brand marks use a 256 × 256 transparent canvas; brand lockups use 720 × 288.
- Client logos use a 360 × 160 transparent canvas, preserving a consistent 9:4 visual area.
- The navbar renders the official surface-specific brand lockup at 320 intrinsic pixels instead of composing the brand mark with a system-font `SaltaCode` label.
- The hero loads one surface-specific vector lockup recovered from the historical production artwork. Each animated SVG is 26,527 raw bytes and 4,841 bytes over the local server's negotiated gzip response; reduced-motion visitors receive a static 13,627-byte vector instead of downloading or running the animation.
- The client carousel keeps one complete, indexable logo group in static HTML. A small progressive enhancement clones that group with `aria-hidden` only when motion is allowed, so the infinite loop adds no duplicate asset transfer; reduced-motion visitors retain one horizontally scrollable group.

The source-to-output mapping, dimensions, byte sizes, and SHA-256 hashes live in `frontend/src/assets/optimized/manifest.json`.

## Generation and validation

Run:

```bash
pnpm --dir frontend assets:generate
pnpm --dir frontend assets:check
```

`assets:generate` uses pinned Sharp transforms and lossless WebP output. `assets:check` regenerates every variant in memory and fails on byte drift, missing files, manifest drift, or unexpected generated files.

The build gate also requires:

- exactly two brand assets and eleven displayed clients;
- both surface variants for every asset;
- the canonical canvases above;
- no variant larger than 32 KiB;
- no more than 260 KiB for the complete 26-variant library;
- eager low-priority loading, asynchronous decoding, and explicit 180 × 80 rendered dimensions for all animated client logos so Firefox never decodes an incoming logo mid-motion.
- one accessible client group, pause on keyboard focus, and a non-animated reduced-motion fallback.

## Verified sources

- Saltacode mark and lockup variants were recovered from the repository's legacy commit `b6562bfa`.
- The animated hero lockup preserves the verified paths, gradient stops, vector wordmark, tagline, drawing order, easing, and delays from that commit's `index.html`, `assets/css/logo-animated.css`, and `assets/js/hero-logo-animated.js`. The historical 72,606-byte inline source was converted into hashed light/dark external assets, scoped animations, fixed dimensions, and dedicated static reduced-motion variants; it adds no font request and the selected response is compressed by the static server.
- Metalnor uses its official first-party lockup as the shared source for both themes. A luminance-derived ink mask preserves the globe, arrows, and wordmark detail before applying the common client palette; flattening the complete alpha channel produced an unreadable solid emblem.
- Cocel uses the provided variants verified against the first-party `website-cocel` working copy.
- Every client, including Metalnor and Cocel, is converted to the shared monochrome palette without changing its geometry: `#74747D` on light surfaces and `#D8D8E0` on dark surfaces.
- Finanx keeps its original source intact; the deterministic generator removes its uniform source background before producing the two monochrome surface variants.

Generative AI is not used for logos. Verified official variants exist, and synthesizing a trademark would introduce brand and provenance risk rather than improve quality.

## Adding a client

1. Obtain an authorized, high-resolution transparent source.
2. Add explicit `onLight` and `onDark` source mappings to `frontend/scripts/generate-theme-assets.mjs`.
3. Add the generated imports and client entry to `frontend/src/data/image-assets.ts`.
4. Regenerate the library, inspect both surfaces, and run the frontend test suite.

Do not infer, redraw, or generate a missing company logo. Keep its status unknown until an authorized source is available.
