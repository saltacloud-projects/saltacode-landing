import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const dist = resolve(import.meta.dirname, "../dist");
const index = await readFile(resolve(dist, "index.html"), "utf8");
const robots = await readFile(resolve(dist, "robots.txt"), "utf8");
const sitemap = await readFile(resolve(dist, "sitemap.xml"), "utf8");

const assertions = [
  [/<html lang="es-AR">/, "document language"],
  [/<link rel="canonical" href="https:\/\/saltacode\.com\.ar\/">/, "canonical URL"],
  [/<meta name="description" content="[^"]+">/, "meta description"],
  [/<meta property="og:image" content="https:\/\/saltacode\.com\.ar\/images\/social\/saltacode-social\.webp">/, "OpenGraph image"],
  [/<meta name="twitter:card" content="summary_large_image">/, "Twitter card"],
  [/<script type="application\/ld\+json">\{/, "JSON-LD"],
  [/href="mailto:saltacodear@gmail\.com"/, "email contact path"],
  [/href="https:\/\/wa\.me\/5493875296587/, "WhatsApp contact path"],
];

for (const [pattern, label] of assertions) {
  if (!pattern.test(index)) {
    throw new Error(`Missing required build output: ${label}`);
  }
}

const structuredDataMatch = index.match(/<script type="application\/ld\+json">([^<]+)<\/script>/);
if (!structuredDataMatch) {
  throw new Error("The production page does not contain parseable JSON-LD.");
}

const structuredData = JSON.parse(structuredDataMatch[1]);
if (structuredData["@id"] !== "https://saltacode.com.ar/#organization") {
  throw new Error("JSON-LD does not use the canonical organization identifier.");
}

if ((index.match(/<h1(?:\s|>)/g) ?? []).length !== 1) {
  throw new Error("The landing page must render exactly one h1.");
}

if (!robots.includes("Allow: /") || !robots.includes("https://saltacode.com.ar/sitemap.xml")) {
  throw new Error("robots.txt does not expose the production sitemap.");
}

if (!sitemap.includes("<loc>https://saltacode.com.ar/</loc>")) {
  throw new Error("sitemap.xml does not contain the canonical home URL.");
}

const executableScripts = [...index.matchAll(/<script\b(?![^>]*type="application\/ld\+json")[^>]*>/g)];
if (executableScripts.length !== 0) {
  throw new Error("The static landing page unexpectedly ships executable JavaScript.");
}

console.log("Verified static HTML, canonical metadata, crawl files, contacts, and zero client JavaScript.");
