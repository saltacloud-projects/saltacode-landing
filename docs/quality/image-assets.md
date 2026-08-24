# Image asset contract

This contract covers Saltacode brand images and the client logos currently rendered by the landing page. About and service photography are intentionally outside this pass.

## Surface variants

- `onLight` is the variant for a light surface.
- `onDark` is the variant for a dark surface.
- The current page renders `onLight` only. Runtime light/dark/system theme switching is prepared but intentionally not implemented.
- Brand marks use a 256 × 256 transparent canvas; brand lockups use 720 × 288.
- Client logos use a 360 × 160 transparent canvas, preserving a consistent 9:4 visual area.

The source-to-output mapping, dimensions, byte sizes, and SHA-256 hashes live in `frontend/src/assets/optimized/manifest.json`.

## Generation and validation

Run:

```bash
pnpm --dir frontend assets:generate
pnpm --dir frontend assets:check
```

`assets:generate` uses pinned Sharp transforms and lossless WebP output. `assets:check` regenerates every variant in memory and fails on byte drift, missing files, manifest drift, or unexpected generated files.

The build gate also requires:

- exactly two brand assets and eight displayed clients;
- both surface variants for every asset;
- the canonical canvases above;
- no variant larger than 32 KiB;
- no more than 220 KiB for the complete 20-variant library;
- lazy loading and explicit 180 × 80 rendered dimensions for all client logos.

## Verified sources

- Saltacode mark and lockup variants were recovered from the repository's legacy commit `b6562bfa`.
- Metalnor uses the provided dark-surface logo and the official light-surface logo from the first-party `sistema-metalnor` working copy.
- Cocel uses the provided variants verified against the first-party `website-cocel` working copy.
- The six historical client logos are converted to consistent monochrome surface variants without changing their geometry.

Generative AI is not used for logos. Verified official variants exist, and synthesizing a trademark would introduce brand and provenance risk rather than improve quality.

## Adding a client

1. Obtain an authorized, high-resolution transparent source.
2. Add explicit `onLight` and `onDark` source mappings to `frontend/scripts/generate-theme-assets.mjs`.
3. Add the generated imports and client entry to `frontend/src/data/image-assets.ts`.
4. Regenerate the library, inspect both surfaces, and run the frontend test suite.

Do not infer, redraw, or generate a missing company logo. Keep its status unknown until an authorized source is available.
