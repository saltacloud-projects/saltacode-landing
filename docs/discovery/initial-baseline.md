# Initial repository baseline (historical: 2026-08-23)

This immutable-in-intent snapshot records verified local repository evidence **before** modernization began. It does not describe the current repository architecture and does not certify the live production environment.

## Scope and method

The audit inspected tracked files, active HTML references, local file sizes, image metadata, and repository configuration. It did not authenticate to GitHub or Cloudflare, deploy code, query Search Console, or measure the live site.

## Verified architecture

| Area | Evidence |
|---|---|
| Entry point | One static `index.html`, 2,682 lines and 161,815 bytes. |
| Tracked content | 4,109 tracked files; 3,969 are under `assets/vendor/`. |
| Root build tooling | No root `package.json`, lockfile, build script, or framework configuration. |
| Automated quality | No project test suite or CI workflow existed at baseline. |
| Hosting configuration | No Cloudflare Pages, Wrangler, Docker, Netlify, or Vercel configuration existed at baseline. |
| Contact paths | WhatsApp and `mailto:` links; no active lead form backend. |
| Analytics | No analytics tag was found in tracked page or project JavaScript. |

The page uses checked-in Bootstrap 5.2.3, Boxicons 2.1.4, Smooth Scroll 16.1.3, Rellax 1.12.1, and Swiper 8.4.5 assets.

## Verified SEO gaps

- The root element declares `lang="en"` while visible content is Spanish.
- The head contains two title elements.
- The active page has no `h1`.
- `og:image` and `twitter:image` are empty.
- Canonical and OpenGraph use `https://www.saltacode.com.ar/`, while Twitter URL/domain metadata uses `.com`.
- No JSON-LD structured data was found.
- No `robots.txt` or sitemap exists in the repository.

The canonical itself points to the intended `.com.ar` homepage in the repository. Whether redirects and headers preserve that intent in production remains unknown.

## Verified performance risks

| Risk | Local evidence |
|---|---|
| HTML weight | About 162 KB, including a large inline SVG and legacy comments. |
| Referenced local payload | About 5.96 MB of raw local files referenced by active HTML, before CSS background assets and external fonts. |
| Largest hero asset | `screens01.png` is about 1.99 MB. |
| Service image dimensions | Four WebP service images are approximately 7,000 px square. |
| Image loading | Active images do not use `loading="lazy"` or `decoding="async"`; many omit explicit dimensions. |
| Render timing | The visible preloader is removed from a `window.load` handler. |
| Duplicate resources | Swiper CSS, Montserrat, and Nexa declarations are repeated in the head. |
| Bundle scope | Full theme and Swiper bundles are loaded for a comparatively small single page. |

These are risks, not measured Core Web Vitals. Compression, caching, CDN behavior, device class, and field performance were not verified.

## Known unknowns

- Current host, Cloudflare zone/Pages project, DNS, redirects, response headers, cache policy, compression, and deployment pipeline.
- GitHub branch protections, Actions configuration, secrets, and authenticated repository state.
- Google Search Console ownership, indexed URLs, crawl errors, queries, backlinks, and manual actions.
- Real-user LCP, INP, and CLS; current Lighthouse and PageSpeed Insights results.
- Conversion volume, privacy/consent requirements, and analytics ownership.

## Next discovery gate

The first public-response and synthetic mobile checks are recorded in [`production-baseline.md`](production-baseline.md). Before production cutover, complete the remaining read-only evidence for authenticated deployment ownership and configuration, Search Console coverage and selected canonical, CrUX field Core Web Vitals, repeatable multi-run lab measurements, structured-data validation, and rollback controls.

## Post-baseline repository state

The repository now contains an Astro static frontend, FastAPI BFF, private agent seed, versioned chat contracts, Compose topology, host-managed Tunnel templates, CI, and agentic validation. Those changes supersede this document as a description of the repository, but they do not prove that production has changed.

Use the current tracked files, [`../architecture/technology-direction.md`](../architecture/technology-direction.md), and [`../architecture/platform-topology.md`](../architecture/platform-topology.md) for implemented architecture. Keep live deployment, DNS, Cloudflare, indexing, rankings, and field Core Web Vitals unknown until verified directly.
