# Modernization readiness — 2026-08-24

The repository candidate through `cbffd0f8` passes its local build, contract, container, SEO, accessibility, and performance gates. It is **not yet a production release**: no DNS, Tunnel, Cloudflare, systemd, provider, or public deployment state was changed during this work.

## Outcome

| Area | Local result | Evidence boundary |
|---|---|---|
| Frontend | PASS | Astro check/build/runtime verification; deterministic asset budgets. |
| Technical SEO | PASS with external gates | Static Spanish HTML, apex canonical, one `h1`, schema, crawl files, real 404, legacy fragment aliases, and `/index.html` normalization. |
| Lighthouse | PASS | Three local mobile and three local desktop runs met `100/100/100/100`. |
| Public BFF | PASS | Ruff, schema drift, **35 tests**, non-root image, Redis fail-closed behavior. |
| Private agent seed | PASS as a scaffold | Ruff, **20 tests**, non-root image; real provider, RAG, and tool adapters intentionally remain absent. |
| Infrastructure | PASS as a model | Shell syntax, production/sandbox Compose config, Tunnel ingress ordering, systemd templates, and preflight. No services were installed or promoted. |
| Agentic layer | PASS | Six agents and ten skills validated. |

Passing this table proves repository and local candidate behavior only. It does not prove indexing, rankings, public redirects, field Core Web Vitals, provider ownership, or rollback readiness.

## SEO changes

| Legacy evidence | Candidate behavior |
|---|---|
| Document language declared as English. | `lang="es-AR"`. |
| Checked-in canonical used `www` while the public host redirected to apex. | Canonical, OpenGraph URL, JSON-LD, robots, and sitemap use `https://saltacode.com.ar/`. |
| Public sitemap returned 404. | Build emits a valid apex sitemap; public delivery still requires verification. |
| `/index.html` returned 200. | `GET` and `HEAD` permanently redirect to `/` and preserve the query string. |
| English section fragments were externally addressable. | Six legacy fragments map to the new Spanish IDs without focus or layout changes. |
| Monolithic HTML and vendored demo pages were active repository sources. | Astro is the single source; unknown routes return a real branded 404. |
| Social preview source was square and oversized. | OpenGraph/Twitter use a reviewed 1200 × 630 WebP under 21 KiB. |

The removed vendor tree contained 19 demo HTML pages. The new runtime returns 404 for them. Before cutover, inspect Search Console and backlinks; use 410 only when evidence confirms that an obsolete URL should disappear, and never redirect technical junk to the homepage.

## Performance evidence

### Final Lighthouse candidate

Lighthouse 13.4.1 ran against the local Node origin with a cold profile. All three runs in each mode scored:

| Mode | Performance | Accessibility | Best Practices | SEO | LCP range | TBT | CLS |
|---|---:|---:|---:|---:|---:|---:|---:|
| Mobile | 100 | 100 | 100 | 100 | 1.352–1.355 s | 0 ms | 0 |
| Desktop | 100 | 100 | 100 | 100 | 0.342–0.344 s | 0 ms | 0 |

The build gate recorded 17,378 bytes of home HTML, 11,893 bytes of CSS, zero executable JavaScript, zero webfonts, and a 20,640-byte social image. Independent throttled Chrome runs measured less than 100 KiB initial transfer and less than 147 KiB after a full scroll.

### Directional legacy comparison

The 2026-08-23 public legacy run recorded 62 requests, 5.56 MB transferred, 28.16 s LCP, and 0.245 CLS. The Astro local run recorded 11–12 initial requests, about 89–97 KiB transferred, approximately 0.52 s instrumented LCP, and zero CLS.

This comparison is strongly positive but not equivalent: the legacy measurement used the public path while the candidate measurement used a local origin and different tooling. Only a deployed preview measured under identical conditions can prove the production delta.

## Production gates

1. Resolve and inspect the immutable Redis image digest plus its runtime UID/GID.
2. Deploy a preview without changing production DNS, then repeat Lighthouse, link, metadata, schema, contact, 404, and chat-boundary checks.
3. Verify HTTP-to-HTTPS and `www`-to-apex as single permanent redirects that preserve paths and query strings.
4. Verify public `robots.txt`, sitemap, canonical, `/index.html`, response compression, cache headers, and Cloudflare status after routing through the Tunnel.
5. Export Search Console coverage and backlink evidence before deciding the 19 obsolete vendor URLs; retain aggregated privacy-safe evidence.
6. Confirm that the published address, telephone, social profiles, and historical client logos remain accurate and authorized.
7. Capture the current provider route and rollback point before retiring the existing production origin.
8. Keep chat disabled or visibly unavailable until the approved provider, knowledge, tools, privacy, retention, quote, and escalation contracts are implemented and tested.
9. After promotion, monitor Search Console and field LCP, INP, and CLS at the 75th percentile before claiming a ranking or real-user performance improvement.

## Risk conclusion

The code changes have a direct, measurable positive effect on crawlable HTML, URL consistency, payload, rendering work, and local lab quality. The remaining SEO risk is concentrated at the production edge and migration boundary: redirects, Cloudflare-managed robots, cache/compression behavior, obsolete URLs, current business facts, and Search Console state. A careless cutover can still erase the local gains, so promotion remains an evidence-gated and explicitly authorized operation.

Related evidence:

- [`production-baseline.md`](production-baseline.md)
- [`../quality/seo-performance-contract.md`](../quality/seo-performance-contract.md)
- [`../architecture/platform-topology.md`](../architecture/platform-topology.md)
- [`../../infrastructure/README.md`](../../infrastructure/README.md)
