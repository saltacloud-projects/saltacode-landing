import type { APIRoute } from "astro";
import { publicRoutes } from "../data/site-content";

export const prerender = true;

export const GET: APIRoute = ({ site }) => {
  if (!site) {
    throw new Error("Astro site must be configured to generate sitemap.xml.");
  }

  const urls = publicRoutes
    .map((route) => `  <url>\n    <loc>${new URL(route, site).href}</loc>\n  </url>`)
    .join("\n");
  const body = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls}
</urlset>
`;

  return new Response(body, {
    headers: {
      "Content-Type": "application/xml; charset=utf-8",
    },
  });
};
