---
name: performance-budget
description: "Trigger: performance, Core Web Vitals, Lighthouse, payload, hydration. Baseline and enforce measurable performance budgets."
license: Apache-2.0
metadata:
  author: "Oscar Vargas"
  version: "1.0"
---

## Activation Contract

Load this skill for framework, component, script, font, image, third-party, animation, or hosting changes that can affect rendering or interaction.

## Hard Rules

- Separate code risk, lab measurements, and 75th-percentile field data.
- Use comparable device, network, location, route, cache state, and run count.
- Baseline before enforcing numeric budgets; never raise a budget only to make CI pass.
- Treat Lighthouse targets as engineering gates, not ranking guarantees.

## Decision Gates

| Data | Action |
|---|---|
| Sufficient field data | Judge LCP, INP, and CLS at p75. |
| No field data | Use repeatable lab runs and disclose the limitation. |
| New third party or island | Measure isolated and total-page cost. |
| Regression variance | Repeat runs before concluding. |

## Execution Steps

1. Inventory initial HTML, critical CSS, JavaScript, fonts, LCP media, third parties, and main-thread work.
2. Capture representative baseline runs and medians.
3. Compare against field targets and Lighthouse lab targets.
4. Attribute regressions to specific resources or tasks.
5. Define or update reviewed budgets and release evidence.

## Output Contract

Return measurement conditions, raw and summarized results, budget pass/fail, likely causes, confidence, and missing field evidence.

## References

- `../../../docs/quality/seo-performance-contract.md`
- `../../../docs/discovery/initial-baseline.md`
