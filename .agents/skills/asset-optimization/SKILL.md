---
name: asset-optimization
description: "Trigger: image optimization, fonts, CSS, JavaScript, asset pipeline. Reduce transfer, decode, and render cost without visual regressions."
license: Apache-2.0
metadata:
  author: "Oscar Vargas"
  version: "1.0"
---

## Activation Contract

Load this skill when adding or changing images, icons, fonts, animations, stylesheets, scripts, or bundling behavior.

## Hard Rules

- Preserve source assets until optimized output is visually and functionally verified.
- Use responsive dimensions and formats; do not serve oversized media for its rendered slot.
- Do not lazy-load the actual LCP image. Lazy-load below-fold media and reserve dimensions.
- Avoid adding a client runtime for build-time asset work.

## Decision Gates

| Asset | Preferred treatment |
|---|---|
| LCP image | Responsive source, explicit dimensions, preload only when measured useful. |
| Below-fold image | Responsive output, lazy loading, async decode. |
| Decorative image | CSS or empty alternative; exclude from accessibility tree. |
| Font | Subset/self-host when licensing permits; limit weights and preload carefully. |
| Script/CSS | Import only used code; defer non-critical behavior. |

## Execution Steps

1. Record source size, dimensions, format, usage, and render slot.
2. Generate right-sized variants and retain quality evidence.
3. Add width/height or aspect ratio, loading priority, and meaningful alternative text.
4. Measure transfer, decode, layout, and visual impact.
5. Remove obsolete generated assets only after reference checks.

## Output Contract

Return before/after bytes and dimensions, markup or pipeline changes, visual/accessibility checks, and measured page impact.

## References

- `../../../docs/discovery/initial-baseline.md`
- `../../../docs/quality/seo-performance-contract.md`
