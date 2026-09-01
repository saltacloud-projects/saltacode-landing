# SEO and performance contract

Every modernization change must preserve indexability and established public behavior while moving measured performance toward explicit targets. Passing these checks does not guarantee search rankings.

## SEO invariants

- Preserve existing public URLs and canonical intent. Add tested permanent redirects before removing or renaming an indexed URL.
- Serve primary marketing copy, headings, navigation, and contact information as static indexable HTML.
- Keep one descriptive title, one meaningful `h1`, accurate Spanish language metadata, unique descriptions, canonical URL, and complete OpenGraph/Twitter previews.
- Generate and validate `robots.txt`, sitemap, and applicable JSON-LD from the same production URL source.
- Keep status codes, redirect chains, trailing-slash policy, host normalization, and `www` policy explicit.
- Never block production crawling through a preview-only `noindex` rule, robots rule, authentication gate, or framework fallback.
- Validate internal links and preserve non-chat contact paths.

## Core Web Vitals field targets

Evaluate mobile and desktop field data at the 75th percentile when sufficient traffic exists:

| Metric | Target |
|---|---|
| LCP | <= 2.5 seconds |
| INP | <= 200 milliseconds |
| CLS | <= 0.1 |

When field data is unavailable, report that limitation and use repeatable lab measurements as provisional evidence.

## Lighthouse lab targets

Use consistent device, network, location, route, and run count:

| Category | Target |
|---|---|
| Performance | >= 95 |
| Accessibility | >= 95 |
| Best Practices | >= 95 |
| SEO | 100 |

These are engineering quality gates, not ranking guarantees. Scores can vary between runs and do not replace Search Console or field Core Web Vitals.

## Performance budgets

Version 8 of the provisional local budgets extends the repeatable 2026-08-24 Astro preview baseline with individual service routes, official brand icons, the deferred privacy center, service shortcuts, and consent-scoped chat continuity. Homepage-critical CSS, interior-only CSS, non-chat JavaScript, chat, and privacy assets are measured separately so an interior route or deferred feature cannot silently consume the initial-page allowance. Initial JavaScript includes static imports of each HTML entry, not only the directly referenced files. Build-only limits are enforced by `frontend/scripts/verify-build.mjs`; transfer limits remain browser-lab release gates.

| Resource or scenario | Version 8 limit | Gate |
|---|---:|---|
| Generated home HTML | <= 29.25 KiB raw | Deterministic build assertion |
| Homepage core CSS | <= 20 KiB raw | Deterministic build assertion |
| Additional interior-route CSS | <= 5 KiB raw | Deterministic build assertion |
| Initial executable JavaScript | <= 5.5 KiB raw | Deterministic build assertion |
| Non-chat executable JavaScript | <= 7 KiB raw | Deterministic build assertion |
| Lazy chat chunk | <= 23 KiB raw | Deterministic build assertion |
| Deferred privacy JavaScript | <= 3 KiB raw | Deterministic build assertion |
| Deferred privacy CSS | <= 4 KiB raw | Deterministic build assertion |
| Emitted webfonts | 0 bytes | Deterministic build assertion |
| Social preview image | <= 100 KiB raw | Deterministic build assertion |
| Cold initial-page transfer | <= 125 KiB encoded | Repeatable browser lab |
| Cold full-scroll transfer | <= 175 KiB encoded | Repeatable browser lab |

The browser-lab gates require consistent viewport, network, CPU, cache state, route, and run count. Record the median and raw runs. Lighthouse scores, public-origin compression and cache behavior, and 75th-percentile field data are separate evidence and must still be verified.

The reviewed theme delta is +4,681 bytes of raw home HTML, +2,834 bytes of emitted CSS, and +1,927 bytes of initial and total executable JavaScript versus the circuit-hero baseline. It covers three explicit accessible theme choices, the pre-paint system/saved-preference bootstrap, duplicate-download prevention for theme images, optimized light/dark image source metadata, cross-tab/system synchronization, and the shared page-shell controller.

The 2026-08-24 post-theme mobile browser lab used Chrome 150 at 390x844, 150 ms latency, 1.6 Mbps download, 750 Kbps upload, 4x CPU throttling, disabled cache, and three cold runs per explicit theme. Light mode recorded 127,857 bytes in every run, 588/596/604 ms LCP, 33/35/44 ms TBT, and 0 CLS; dark mode recorded 125,289 bytes in every run, 596/600/608 ms LCP, 29/33/39 ms TBT, and 0 CLS. Every run used only the selected image variants, had no horizontal overflow or runtime exceptions, and passed the provisional cold initial-transfer gate. Production compression, field data, and Lighthouse remain separate release evidence.

The historical-lockup correction replaces the simplified inline approximation with the production paths, gradients, vector wordmark, tagline, drawing sequence, easing, and delays. It adds no font request, renders at 220 CSS pixels instead of 300, emits only the selected theme variant, and swaps to a static exact vector before paint when reduced motion is preferred. That checkpoint build was 27,302 bytes of HTML, 18,306 bytes of CSS, 4,325 bytes of initial JavaScript, and 12,625 bytes of total JavaScript, leaving 346, 126, 795, and 1,711 bytes of headroom respectively without raising a limit.

The exact animated vectors are 26,527 raw bytes per theme. Before origin compression, the equivalent mobile lab transferred 140,989 bytes in light mode and 138,625 bytes in dark mode, exceeding the 128,000-byte cold-transfer gate even though CLS remained 0. The limit was not raised: the Node static server now negotiates gzip for compressible responses and emits `Vary: Accept-Encoding`; the selected animated SVG transfers 4,841 bytes locally.

The final post-compression mobile lab used the same conditions and three cold runs per explicit theme. Light mode recorded 81,089 bytes in every run, 480/492/500 ms LCP, 31/35/58 ms TBT, and 0 CLS; dark mode recorded 78,725 bytes in every run, 488/500/504 ms LCP, 21/28/37 ms TBT, and 0 CLS. No run fetched the wrong theme variant, overflowed horizontally, or raised a runtime exception. This is local lab evidence only; public Cloudflare compression, field data, and Lighthouse remain release-stage checks.

The responsive-navbar and client-carousel change uses the official themed brand lockup, moves the single static client section into the hero, removes the four duplicated service-summary cards, and progressively creates the second carousel group only in browsers that allow motion. The carousel uses a compositor-promoted 3D transform rather than a new dependency or hydrated island, pauses on keyboard focus, and stays static when reduced motion is preferred. Firefox-specific inspection found its native lazy-loading policy left an offscreen logo undecoded while the track was already moving; every small carousel logo now loads eagerly at low priority and decodes asynchronously. The former CSS mask and backface layer were replaced by a stationary gradient overlay so Firefox does not composite a moving masked surface. All eleven clients now share the deterministic theme palette, including Metalnor and Cocel. The current build is 26,825 bytes of HTML, 18,407 bytes of CSS, 4,813 bytes of initial JavaScript, and 13,113 bytes of total JavaScript, leaving 823, 25, 307, and 1,223 bytes of headroom respectively without raising a limit. The complete 26-variant image library fell from 249,650 to 210,412 bytes after normalizing the two exceptional logos.

The approved mobile navigation replaces a 415px horizontal link row inside a 348px viewport with one native disclosure, four vertical 46px targets, the complete theme control, and the existing contact CTA. The exact attributed delta is +644 bytes of home HTML, +982 bytes of CSS, and +259 bytes of initial and total JavaScript; the resulting build is 27,469 bytes of HTML, 19,401 bytes of CSS, 5,072 bytes of initial JavaScript, and 13,372 bytes total. The CSS budget was reviewed from 18 to 20 KiB for this user-facing navigation rather than raised to mask an unexplained regression; the JavaScript and transfer budgets were not raised.

The footer redesign replaces the improvised mark-plus-system-text signature with the official themed lockup and adds static service, company, contact, location, and social destinations. Its attributed delta is +1,158 bytes of home HTML and +748 bytes of CSS with no JavaScript increase; the build is 28,627 bytes of HTML and 20,149 bytes of CSS. The HTML cap was reviewed from 27 to 29 KiB for the new indexable directory and verified contact paths; CSS remains inside the already reviewed 20 KiB allowance and transfer limits remain unchanged.

The 2026-08-27 multipage and chat-consent checkpoint keeps the conversion homepage static while adding substantial Services, About, Contact, Privacy, Cookies, and Terms routes. The build records 27,596 bytes of home HTML, 20,352 bytes of homepage CSS, 4,275 bytes of interior-only CSS, 5,075 bytes of initial JavaScript, 6,412 bytes of non-chat JavaScript, and a 13,670-byte lazy chat chunk. The chat code is requested only after interaction; the interior stylesheet is not linked from the homepage. The split budgets make that isolation testable instead of raising a single aggregate limit that could hide critical-path growth. Public transfer measurements and field Core Web Vitals remain release-stage evidence and were not inferred from these raw build sizes.

The 2026-08-28 service, brand-icon, and privacy checkpoint builds eleven indexable routes and records 29,681 bytes of home HTML, 20,315 bytes of homepage CSS, 5,076 bytes of interior CSS, 5,235 bytes of initial JavaScript including its static module dependency, 6,572 bytes of non-chat JavaScript, a 16,244-byte lazy chat chunk, a 1,789-byte deferred privacy chunk, and 3,752 bytes of deferred privacy CSS. The initial allowance was reviewed from 5 to 5.25 KiB only after the verifier was corrected to count the 1,342-byte static preload helper reached by the page-shell module; the actual feature delta remained bounded and privacy UI assets retain independent limits. Brand marks are a cacheable 5,677-byte SVG sprite instead of duplicated inline paths. These are raw local build measurements, not public transfer or field-performance claims.

The service-shortcut checkpoint attributes an additional 123 bytes of home HTML, 24 bytes of homepage CSS, and 175 bytes of initial/non-chat JavaScript to four native submit controls that route a contextual service intent through the existing consent-aware launcher. The resulting build records 29,804 bytes of home HTML, 20,339 bytes of homepage CSS, 5,410 bytes of initial JavaScript, and 6,747 bytes of non-chat JavaScript; the lazy chat and privacy chunks are unchanged. The reviewed HTML and initial-JavaScript limits move to 29.25 KiB and 5.5 KiB respectively for this explicit interaction, not for an unexplained regression. Transfer and field Core Web Vitals remain separate release evidence.

The 2026-09-01 chat-continuity checkpoint keeps first-visit chat code lazy and attributes a 6,565-byte raw increase to the prior 16,244-byte chat chunk. The resulting 22,809-byte chunk adds a versioned 30-day local transcript with 80-message/64-KiB bounds, corruption and quota tolerance, interrupted-stream recovery without automatic replay, a persistent accessible reopen control, the disclosed WhatsApp channel boundary, and mobile dialog/composer corrections. The reviewed lazy-chat limit moves from 16 to 23 KiB for that isolated functionality. Initial executable JavaScript remains within its existing 5.5-KiB cap at 5,589 bytes because returning-session detection only schedules the dynamic chat import when the transcript key exists. No initial-page transfer or field-performance improvement is inferred from these raw build figures.

The last complete Chrome 150 mobile lab before that markup-only cleanup used 390x844, 150 ms latency, 1.6 Mbps download, 750 Kbps upload, 4x CPU throttling, disabled cache, and three cold runs per explicit theme. Light mode transferred 67,656 bytes in every run with 480/484/564 ms LCP, 21/28/48 ms TBT, and 0 CLS; dark mode transferred 66,642 bytes in every run with 476/488/564 ms LCP, 20/24/47 ms TBT, and 0 CLS. Functional checks at 320px, 390px, and 1440px found no horizontal document overflow, wrong theme variant, duplicate accessible client group, or runtime exception. The cleanup was verified against the rebuilt served HTML and static budgets, but the full throttled lab was not rerun. These remain local lab results, not public field evidence.

The initial JavaScript allowance covers the CSP-hashed pre-paint theme bootstrap, shared theme/navigation controller, and fingerprinted hero loader. Motion mini and the circuit controller stay in one separate dynamic chunk requested after browser idle and are not requested when reduced motion is preferred. The 404 route may execute only the same CSP-hashed theme bootstrap and shared controller required to honor the persisted preference; `unsafe-inline` and `unsafe-eval` remain prohibited everywhere.

Budget changes require measured evidence and review. Never raise a limit only to make CI pass; first attribute the regression and either remove it or document the reviewed tradeoff.

## Accessibility contract

- Use semantic landmarks and a logical heading hierarchy.
- Preserve keyboard operation, visible focus, skip navigation, reduced-motion behavior, and sufficient contrast.
- Give informative images meaningful alternatives and decorative images empty alternatives.
- Announce chat state and streamed responses without stealing focus.
- Test automated rules plus keyboard and screen-reader critical paths; automated scores alone are insufficient.

## Release evidence

For each release candidate, record changed URLs, redirects, metadata/schema diff, robots/sitemap result, link validation, Lighthouse runs, accessibility checks, asset-budget result, console/network errors, and rollback point. Verify the deployed response, not only the build output.

The scheduled public observability workflow reuses `infrastructure/scripts/verify-public.sh` as a daily, external, state-neutral regression signal for the deployed HTTP contract. Its result is operational evidence for the checks implemented by that script only. It is not ranking evidence, does not query Search Console, and does not collect mobile or desktop Core Web Vitals at the 75th percentile. Those provider and field-data checks remain manual evidence gates until a separately reviewed, privacy-safe data source is configured.
