import { readdir, readFile } from "node:fs/promises";
import { extname, relative, resolve } from "node:path";

const dist = resolve(import.meta.dirname, "../dist");
const routeFiles = new Map([
  ["/", "index.html"],
  ["/servicios/", "servicios/index.html"],
  ["/nosotros/", "nosotros/index.html"],
  ["/contacto/", "contacto/index.html"],
  ["/legal/privacidad/", "legal/privacidad/index.html"],
  ["/legal/cookies/", "legal/cookies/index.html"],
  ["/legal/terminos/", "legal/terminos/index.html"],
]);
const pages = new Map(
  await Promise.all([...routeFiles].map(async ([route, file]) => [route, await readFile(resolve(dist, file), "utf8")])),
);
const index = pages.get("/");
const indexBuffer = await readFile(resolve(dist, "index.html"));
const notFound = await readFile(resolve(dist, "404.html"), "utf8");
const robots = await readFile(resolve(dist, "robots.txt"), "utf8");
const sitemap = await readFile(resolve(dist, "sitemap.xml"), "utf8");
const chatSource = await readFile(resolve(import.meta.dirname, "../src/scripts/chat-preview.ts"), "utf8");
const pageMotionSource = await readFile(resolve(import.meta.dirname, "../src/scripts/page-motion.ts"), "utf8");
const clientMessageIdSource = await readFile(resolve(import.meta.dirname, "../src/scripts/client-message-id.ts"), "utf8");
const assetManifest = JSON.parse(await readFile(resolve(import.meta.dirname, "../src/assets/optimized/manifest.json"), "utf8"));

const BUILD_BUDGETS = Object.freeze({
  indexHtmlBytes: 29 * 1024,
  coreCssBytes: 20 * 1024,
  additionalInteriorCssBytes: 5 * 1024,
  initialExecutableJavaScriptBytes: 5 * 1024,
  nonChatExecutableJavaScriptBytes: 7 * 1024,
  chatChunkBytes: 16 * 1024,
  socialImageBytes: 100 * 1024,
  webfontBytes: 0,
});
const EXECUTABLE_JAVASCRIPT_EXTENSIONS = new Set([".cjs", ".js", ".mjs"]);
const WEBFONT_EXTENSIONS = new Set([".eot", ".otf", ".ttf", ".woff", ".woff2"]);
const EXPECTED_CLIENTS = ["KO-27", "Balance", "V8", "Grupo Kamal", "Planeta Puna", "Óptica Total", "Metalnor", "Cocel", "Finanx", "Coseguro Total", "Mariana Prone"];
const ASSET_LIBRARY_BUDGETS = Object.freeze({ maximumVariantBytes: 32 * 1024, totalVariantBytes: 260 * 1024 });

async function listBuildFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
    const absolutePath = resolve(directory, entry.name);
    if (entry.isDirectory()) files.push(...(await listBuildFiles(absolutePath)));
    else if (entry.isFile()) {
      const contents = await readFile(absolutePath);
      files.push({ bytes: contents.byteLength, extension: extname(entry.name).toLowerCase(), path: relative(dist, absolutePath) });
    }
  }
  return files;
}

const buildFiles = await listBuildFiles(dist);
const fileByPath = new Map(buildFiles.map((file) => [file.path, file]));
const socialImage = fileByPath.get("images/social/saltacode-social.webp");
if (!socialImage) throw new Error("Missing required social preview image.");

function extractLandmark(markup, tag) {
  const match = markup.match(new RegExp(`<${tag}\\b[^>]*>[\\s\\S]*?<\\/${tag}>`));
  if (!match) throw new Error(`Missing required ${tag} landmark.`);
  return match[0];
}
function extractAnchorHrefs(markup) {
  return [...markup.matchAll(/<a\b[^>]*\bhref="([^"]+)"[^>]*>/g)].map((match) => match[1]);
}
function hasId(markup, id) { return new RegExp(`\\bid="${id}"`).test(markup); }
function attributeValue(tag, name) { return tag.match(new RegExp(`\\b${name}="([^"]*)"`))?.[1]; }
function extractExecutableScripts(markup) {
  return [...markup.matchAll(/<script\b(?![^>]*type="application\/ld\+json")([^>]*)>([\s\S]*?)<\/script>/g)];
}
function stylesheetPaths(markup) {
  return new Set([...markup.matchAll(/<link\b(?=[^>]*rel="stylesheet")(?=[^>]*href="([^"]+)")[^>]*>/g)].map((match) => match[1].replace(/^\//, "")));
}
function bytesForPaths(paths) {
  return [...paths].reduce((total, path) => {
    const file = fileByPath.get(path);
    if (!file) throw new Error(`Referenced build asset is missing: ${path}`);
    return total + file.bytes;
  }, 0);
}
function totalBytesForExtensions(extensions) {
  return buildFiles.filter((file) => extensions.has(file.extension)).reduce((total, file) => total + file.bytes, 0);
}

const homeScripts = extractExecutableScripts(index);
const inlineBytes = homeScripts.reduce((total, script) => total + Buffer.byteLength(script[2]), 0);
const initialExternalBytes = homeScripts.reduce((total, script) => {
  const source = attributeValue(script[1], "src");
  return source ? total + (fileByPath.get(source.replace(/^\//, ""))?.bytes ?? 0) : total;
}, 0);
const homeCssPaths = stylesheetPaths(index);
const allRouteCssPaths = new Set([...pages.values()].flatMap((markup) => [...stylesheetPaths(markup)]));
const additionalCssPaths = new Set([...allRouteCssPaths].filter((path) => !homeCssPaths.has(path)));
const chatChunk = buildFiles.find((file) => file.extension === ".js" && /(?:^|\/)chat-preview\.[^/]+\.js$/.test(file.path));
if (!chatChunk) throw new Error("The lazy chat chunk was not emitted.");
const totalJavaScript = totalBytesForExtensions(EXECUTABLE_JAVASCRIPT_EXTENSIONS) + inlineBytes;
const measuredBuild = Object.freeze({
  indexHtmlBytes: indexBuffer.byteLength,
  coreCssBytes: bytesForPaths(homeCssPaths),
  additionalInteriorCssBytes: bytesForPaths(additionalCssPaths),
  initialExecutableJavaScriptBytes: initialExternalBytes + inlineBytes,
  nonChatExecutableJavaScriptBytes: totalJavaScript - chatChunk.bytes,
  chatChunkBytes: chatChunk.bytes,
  socialImageBytes: socialImage.bytes,
  webfontBytes: totalBytesForExtensions(WEBFONT_EXTENSIONS),
});
const budgetResults = [
  ["generated index HTML", measuredBuild.indexHtmlBytes, BUILD_BUDGETS.indexHtmlBytes],
  ["homepage core CSS", measuredBuild.coreCssBytes, BUILD_BUDGETS.coreCssBytes],
  ["additional interior CSS", measuredBuild.additionalInteriorCssBytes, BUILD_BUDGETS.additionalInteriorCssBytes],
  ["initial executable JavaScript", measuredBuild.initialExecutableJavaScriptBytes, BUILD_BUDGETS.initialExecutableJavaScriptBytes],
  ["non-chat executable JavaScript", measuredBuild.nonChatExecutableJavaScriptBytes, BUILD_BUDGETS.nonChatExecutableJavaScriptBytes],
  ["lazy chat chunk", measuredBuild.chatChunkBytes, BUILD_BUDGETS.chatChunkBytes],
  ["social preview image", measuredBuild.socialImageBytes, BUILD_BUDGETS.socialImageBytes],
  ["emitted webfonts", measuredBuild.webfontBytes, BUILD_BUDGETS.webfontBytes],
];
for (const [label, actual, maximum] of budgetResults) console.log(`Build budget: ${label} ${actual} bytes / ${maximum} bytes maximum.`);
const budgetFailures = budgetResults.filter(([, actual, maximum]) => actual > maximum);
if (budgetFailures.length) throw new Error(`Static build performance budget failed: ${budgetFailures.map(([label, actual, maximum]) => `${label}: ${actual} exceeds ${maximum}`).join("; ")}.`);

const homeAssertions = [
  [/<html lang="es-AR">/, "document language"],
  [/<link rel="canonical" href="https:\/\/saltacode\.com\.ar\/">/, "home canonical"],
  [/<meta name="description" content="[^"]+">/, "meta description"],
  [/<meta property="og:image" content="https:\/\/saltacode\.com\.ar\/images\/social\/saltacode-social\.webp">/, "OpenGraph image"],
  [/<meta name="twitter:card" content="summary_large_image">/, "Twitter card"],
  [/<script type="application\/ld\+json">\{/, "JSON-LD"],
  [/data-theme-bootstrap/, "theme bootstrap"],
  [/value="light" data-theme-choice/, "light theme"],
  [/value="dark" data-theme-choice/, "dark theme"],
  [/value="system" data-theme-choice/, "system theme"],
  [/data-circuit-path="core"/, "central circuit trace"],
  [/data-circuit-node="core"/, "central circuit particles"],
  [/data-client-carousel/, "client carousel"],
  [/¿Qué necesitás resolver en tu empresa\?/, "hero prompt"],
  [/href="mailto:saltacodear@gmail\.com"/, "email path"],
  [/href="https:\/\/wa\.me\/5493875296587/, "WhatsApp path"],
  [/Desarrollo de productos SaaS/, "truthful SaaS service title"],
];
for (const [pattern, label] of homeAssertions) if (!pattern.test(index)) throw new Error(`Missing required homepage output: ${label}.`);
if (/Productos SaaS/.test(index)) throw new Error("The obsolete Productos SaaS label must not be rendered.");

const requiredNavigation = ["/", "/#clientes", "/servicios/", "/nosotros/", "/contacto/"];
const requiredLegalLinks = ["/legal/privacidad/", "/legal/cookies/", "/legal/terminos/"];
const titles = new Set();
const descriptions = new Set();
for (const [route, markup] of pages) {
  const title = markup.match(/<title>([^<]+)<\/title>/)?.[1];
  const description = markup.match(/<meta name="description" content="([^"]+)">/)?.[1];
  if (!title || titles.has(title)) throw new Error(`${route} must have a unique title.`);
  if (!description || descriptions.has(description)) throw new Error(`${route} must have a unique description.`);
  titles.add(title); descriptions.add(description);
  if (!markup.includes(`<link rel="canonical" href="https://saltacode.com.ar${route}">`)) throw new Error(`${route} has an invalid canonical.`);
  if ((markup.match(/<h1(?:\s|>)/g) ?? []).length !== 1) throw new Error(`${route} must render exactly one h1.`);
  const navigationMarkup = extractLandmark(markup, "header") + extractLandmark(markup, "footer");
  const hrefs = extractAnchorHrefs(navigationMarkup);
  for (const href of [...requiredNavigation, ...requiredLegalLinks]) if (!hrefs.includes(href)) throw new Error(`${route} navigation is missing ${href}.`);
  if (route !== "/" && !/class="breadcrumbs"/.test(markup)) throw new Error(`${route} must render visible breadcrumbs.`);
  if (/\sstyle="/.test(markup)) throw new Error(`${route} contains a CSP-incompatible inline style attribute.`);
}

const homeHeader = extractLandmark(index, "header");
if (!/<header\b[^>]*\bdata-scroll-header(?:\s|>)/.test(homeHeader)) throw new Error("Homepage header must reveal on scroll.");
for (const [route, markup] of pages) {
  if (route !== "/" && /<header\b[^>]*\bdata-scroll-header(?:\s|>)/.test(extractLandmark(markup, "header"))) throw new Error(`${route} header must remain visible.`);
}

const structuredData = JSON.parse(index.match(/<script type="application\/ld\+json">([^<]+)<\/script>/)?.[1] ?? "null");
if (!structuredData?.["@graph"]?.some((node) => node["@id"] === "https://saltacode.com.ar/#organization")) throw new Error("JSON-LD graph is missing the canonical organization identifier.");
for (const [route, markup] of pages) {
  if (route === "/") continue;
  const data = JSON.parse(markup.match(/<script type="application\/ld\+json">([^<]+)<\/script>/)?.[1] ?? "null");
  if (!data?.["@graph"]?.some((node) => node["@type"] === "BreadcrumbList")) throw new Error(`${route} schema is missing BreadcrumbList.`);
}

const legacyAliases = [["productsAndServices", "servicios", "section"], ["it-consulting", "consultoria-it", "article"], ["saas-solutions", "soluciones-saas", "article"], ["ourCustomers", "clientes", "section"], ["aboutUs", "nosotros", "section"], ["footer", "contacto", "section"]];
for (const [alias, target, element] of legacyAliases) {
  const aliases = index.match(new RegExp(`<span\\b[^>]*\\bid="${alias}"[^>]*>\\s*</span>`, "g")) ?? [];
  if (aliases.length !== 1 || !/class="legacy-fragment-alias"/.test(aliases[0]) || !/aria-hidden="true"/.test(aliases[0])) throw new Error(`Legacy fragment #${alias} must have one neutral alias.`);
  if (!new RegExp(`<${element}\\b[^>]*\\bid="${target}"[^>]*>\\s*<span\\b[^>]*\\bid="${alias}"`).test(index)) throw new Error(`Legacy fragment #${alias} is not mapped to #${target}.`);
}
if (!/<h2 id="clients-title">Nuestros clientes<\/h2>/.test(index)) throw new Error("Clients heading changed unexpectedly.");
if (!/<form\b[^>]*class="agent-preview"[^>]*data-chat-launcher/.test(index)) throw new Error("Hero launcher must remain a semantic form.");
if (!chatSource.includes('const PRIVACY_VERSION = "saltacode-chat-privacy-2026-08-27"') || !chatSource.includes('const CONSENT_STORAGE_KEY = "saltacode-chat-consent"')) throw new Error("Chat consent version or local key is incorrect.");
if (/transcript-consent|type="checkbox"/.test(chatSource)) throw new Error("The chat must not render a persistent consent checkbox.");
if (!chatSource.includes("Aceptar y enviar") || !chatSource.includes("event.isComposing") || !chatSource.includes("AbortController")) throw new Error("Chat first-use, IME, or cancellation safeguards are missing.");
if ([chatSource, pageMotionSource].some((source) => source.includes("crypto.randomUUID"))) throw new Error("Public chat code must not require randomUUID on insecure LAN origins.");
if (!clientMessageIdSource.includes("crypto.getRandomValues") || !clientMessageIdSource.includes("4000-8000")) throw new Error("The browser-compatible UUID v4 generator is missing.");

const clientList = index.match(/<ul class="client-group" data-client-group[^>]*>([\s\S]*?)<\/ul>/)?.[1];
if (!clientList || (index.match(/<ul\b[^>]*\bdata-client-group\b/g) ?? []).length !== 1) throw new Error("Accessible client group is missing or duplicated.");
const clientTags = [...clientList.matchAll(/<img\b[^>]*>/g)].map((match) => match[0]);
const clientNames = clientTags.map((tag) => (attributeValue(tag, "alt") ?? "").replace(/^Logo de /, ""));
if (JSON.stringify(clientNames) !== JSON.stringify(EXPECTED_CLIENTS)) throw new Error(`Unexpected client set: ${clientNames.join(", ")}.`);
for (const tag of clientTags) if (attributeValue(tag, "loading") !== "eager" || attributeValue(tag, "width") !== "180" || attributeValue(tag, "height") !== "80") throw new Error("Client logo loading or dimensions regressed.");

const themeImages = [...index.matchAll(/<img\b(?=[^>]*\bdata-theme-image\b)[^>]*>/g)];
if (themeImages.length !== EXPECTED_CLIENTS.length + 3) throw new Error("Homepage theme images must include every client and three brand lockups.");
for (const [image] of themeImages) if (!/data-theme-src-light="\/_astro\//.test(image) || !/data-theme-src-dark="\/_astro\//.test(image)) throw new Error("Theme image variants are incomplete.");

const animatedLockups = buildFiles.filter((file) => file.extension === ".svg" && file.path.includes("animated-lockup-on"));
const staticLockups = buildFiles.filter((file) => file.extension === ".svg" && file.path.includes("static-lockup-on"));
if (animatedLockups.length !== 2 || staticLockups.length !== 2) throw new Error("The complete animated and reduced-motion lockups must be emitted.");
for (const lockup of animatedLockups) {
  const markup = await readFile(resolve(dist, lockup.path), "utf8");
  if (!/viewBox="0 0 370 152"/.test(markup) || (markup.match(/<animate\b/g) ?? []).length !== 42 || !/prefers-reduced-motion:reduce/.test(markup)) throw new Error(`${lockup.path} lost historical animation invariants.`);
}

if (assetManifest.schemaVersion !== 1 || assetManifest.assets?.length !== 13) throw new Error("Theme image manifest is incomplete.");
let totalAssetVariantBytes = 0;
for (const asset of assetManifest.assets) for (const variant of Object.values(asset.variants)) {
  totalAssetVariantBytes += variant.output.bytes;
  if (variant.output.bytes > ASSET_LIBRARY_BUDGETS.maximumVariantBytes) throw new Error(`${variant.output.path} exceeds its variant budget.`);
}
console.log(`Asset budget: ${totalAssetVariantBytes} bytes / ${ASSET_LIBRARY_BUDGETS.totalVariantBytes} bytes maximum.`);
if (totalAssetVariantBytes > ASSET_LIBRARY_BUDGETS.totalVariantBytes) throw new Error("Theme image library exceeds its budget.");

if (!robots.includes("Allow: /") || !robots.includes("https://saltacode.com.ar/sitemap.xml")) throw new Error("robots.txt is invalid.");
for (const route of routeFiles.keys()) if (!sitemap.includes(`<loc>https://saltacode.com.ar${route}</loc>`)) throw new Error(`sitemap.xml is missing ${route}.`);
for (const legalRoute of ["/legal/privacidad/", "/legal/cookies/", "/legal/terminos/"]) if (!pages.get(legalRoute).includes("27 de agosto de 2026")) throw new Error(`${legalRoute} has no legal version date.`);

if (homeScripts.length !== 3) throw new Error("Homepage must ship the theme bootstrap, page shell and deferred hero loader only.");
const notFoundScripts = extractExecutableScripts(notFound);
if (notFoundScripts.length !== 2 || !notFoundScripts.some((script) => /data-theme-bootstrap/.test(script[1]))) throw new Error("404 script boundary regressed.");
const notFoundLocalFragments = extractAnchorHrefs(notFound).filter((href) => href.startsWith("#"));
if (notFoundLocalFragments.length !== 1 || notFoundLocalFragments[0] !== "#contenido" || !hasId(notFound, "contenido")) throw new Error("404 local fragment behavior regressed.");

console.log(`Verified ${buildFiles.length} files, ${pages.size} indexable routes, metadata, legal content, chat isolation, assets and budgets.`);
