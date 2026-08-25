import { readdir, readFile } from "node:fs/promises";
import { extname, relative, resolve } from "node:path";

const dist = resolve(import.meta.dirname, "../dist");
const indexBuffer = await readFile(resolve(dist, "index.html"));
const index = indexBuffer.toString("utf8");
const notFound = await readFile(resolve(dist, "404.html"), "utf8");
const robots = await readFile(resolve(dist, "robots.txt"), "utf8");
const sitemap = await readFile(resolve(dist, "sitemap.xml"), "utf8");
const assetManifest = JSON.parse(
  await readFile(resolve(import.meta.dirname, "../src/assets/optimized/manifest.json"), "utf8"),
);

const BUILD_BUDGETS = Object.freeze({
  indexHtmlBytes: 27 * 1024,
  cssBytes: 18 * 1024,
  initialExecutableJavaScriptBytes: 5 * 1024,
  totalExecutableJavaScriptBytes: 14 * 1024,
  socialImageBytes: 100 * 1024,
  webfontBytes: 0,
});

const EXECUTABLE_JAVASCRIPT_EXTENSIONS = new Set([".cjs", ".js", ".mjs"]);
const SOCIAL_IMAGE_PATH = "images/social/saltacode-social.webp";
const WEBFONT_EXTENSIONS = new Set([".eot", ".otf", ".ttf", ".woff", ".woff2"]);
const EXPECTED_CLIENTS = [
  "KO-27",
  "Balance",
  "V8",
  "Grupo Kamal",
  "Planeta Puna",
  "Óptica Total",
  "Metalnor",
  "Cocel",
  "Finanx",
  "Coseguro Total",
  "Mariana Prone",
];
const ASSET_LIBRARY_BUDGETS = Object.freeze({
  maximumVariantBytes: 32 * 1024,
  totalVariantBytes: 260 * 1024,
});

async function listBuildFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];

  for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
    const absolutePath = resolve(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await listBuildFiles(absolutePath)));
    } else if (entry.isFile()) {
      const contents = await readFile(absolutePath);
      files.push({
        bytes: contents.byteLength,
        extension: extname(entry.name).toLowerCase(),
        path: relative(dist, absolutePath),
      });
    }
  }

  return files;
}

const buildFiles = await listBuildFiles(dist);
const emittedCss = (
  await Promise.all(
    buildFiles
      .filter((file) => file.extension === ".css")
      .map((file) => readFile(resolve(dist, file.path), "utf8")),
  )
).join("\n");
const socialImage = buildFiles.find((file) => file.path === SOCIAL_IMAGE_PATH);
if (!socialImage) {
  throw new Error(`Missing required build output: ${SOCIAL_IMAGE_PATH}`);
}

function totalBytesForExtensions(extensions) {
  return buildFiles
    .filter((file) => extensions.has(file.extension))
    .reduce((total, file) => total + file.bytes, 0);
}

function extractLandmark(markup, tag) {
  const match = markup.match(new RegExp(`<${tag}\\b[^>]*>[\\s\\S]*?<\\/${tag}>`));
  if (!match) {
    throw new Error(`Missing required ${tag} landmark.`);
  }

  return match[0];
}

function extractAnchorHrefs(markup) {
  return [...markup.matchAll(/<a\b[^>]*\bhref="([^"]+)"[^>]*>/g)].map((match) => match[1]);
}

function hasId(markup, id) {
  return new RegExp(`\\bid="${id}"`).test(markup);
}

function attributeValue(tag, name) {
  return tag.match(new RegExp(`\\b${name}="([^"]*)"`))?.[1];
}

function extractExecutableScripts(markup) {
  return [
    ...markup.matchAll(
      /<script\b(?![^>]*type="application\/ld\+json")([^>]*)>([\s\S]*?)<\/script>/g,
    ),
  ];
}

const homeNavigationFragments = new Set(["top", "clientes", "servicios", "nosotros", "contacto"]);

function verifySharedNavigation(markup, prefix, routeLabel) {
  const navigationMarkup = [extractLandmark(markup, "header"), extractLandmark(markup, "footer")].join(
    "",
  );
  const hrefs = extractAnchorHrefs(navigationMarkup).filter((href) => href.includes("#"));

  if (hrefs.length === 0) {
    throw new Error(`${routeLabel} shared navigation does not contain links.`);
  }

  const resolvedFragments = new Set();
  for (const href of hrefs) {
    const match = href.match(new RegExp(`^${prefix === "/" ? "\\/" : ""}#(.+)$`));
    if (!match || !homeNavigationFragments.has(match[1])) {
      throw new Error(`${routeLabel} shared navigation contains an invalid home link: ${href}`);
    }

    if (!hasId(index, match[1])) {
      throw new Error(`${routeLabel} shared navigation target ${href} is missing from the homepage.`);
    }
    resolvedFragments.add(match[1]);
  }

  for (const fragment of homeNavigationFragments) {
    if (!resolvedFragments.has(fragment)) {
      throw new Error(`${routeLabel} shared navigation is missing the ${prefix}#${fragment} link.`);
    }
  }
}

const homeExecutableScripts = extractExecutableScripts(index);
const inlineExecutableJavaScriptBytes = homeExecutableScripts.reduce(
  (total, script) => total + Buffer.byteLength(script[2]),
  0,
);
const initialExternalJavaScriptBytes = homeExecutableScripts.reduce((total, script) => {
  const source = attributeValue(script[1], "src");
  if (!source) return total;

  const emittedPath = source.replace(/^\//, "");
  const emittedScript = buildFiles.find((file) => file.path === emittedPath);
  if (!emittedScript) throw new Error(`Homepage script ${source} is missing from the build.`);
  return total + emittedScript.bytes;
}, 0);

const measuredBuild = Object.freeze({
  indexHtmlBytes: indexBuffer.byteLength,
  cssBytes: totalBytesForExtensions(new Set([".css"])),
  initialExecutableJavaScriptBytes:
    initialExternalJavaScriptBytes + inlineExecutableJavaScriptBytes,
  totalExecutableJavaScriptBytes:
    totalBytesForExtensions(EXECUTABLE_JAVASCRIPT_EXTENSIONS) + inlineExecutableJavaScriptBytes,
  socialImageBytes: socialImage.bytes,
  webfontBytes: totalBytesForExtensions(WEBFONT_EXTENSIONS),
});

const budgetResults = [
  ["generated index HTML", measuredBuild.indexHtmlBytes, BUILD_BUDGETS.indexHtmlBytes],
  ["total emitted CSS", measuredBuild.cssBytes, BUILD_BUDGETS.cssBytes],
  [
    "initial executable JavaScript",
    measuredBuild.initialExecutableJavaScriptBytes,
    BUILD_BUDGETS.initialExecutableJavaScriptBytes,
  ],
  [
    "total executable JavaScript",
    measuredBuild.totalExecutableJavaScriptBytes,
    BUILD_BUDGETS.totalExecutableJavaScriptBytes,
  ],
  ["social preview image", measuredBuild.socialImageBytes, BUILD_BUDGETS.socialImageBytes],
  ["emitted webfonts", measuredBuild.webfontBytes, BUILD_BUDGETS.webfontBytes],
];

for (const [label, actual, maximum] of budgetResults) {
  console.log(`Build budget: ${label} ${actual} bytes / ${maximum} bytes maximum.`);
}

const budgetFailures = budgetResults.filter(([, actual, maximum]) => actual > maximum);
if (budgetFailures.length > 0) {
  const details = budgetFailures
    .map(([label, actual, maximum]) => `${label}: ${actual} bytes exceeds ${maximum} bytes`)
    .join("; ");
  throw new Error(`Static build performance budget failed: ${details}.`);
}

const assertions = [
  [/<html lang="es-AR">/, "document language"],
  [/<link rel="canonical" href="https:\/\/saltacode\.com\.ar\/">/, "canonical URL"],
  [/<meta name="description" content="[^"]+">/, "meta description"],
  [/<meta property="og:image" content="https:\/\/saltacode\.com\.ar\/images\/social\/saltacode-social\.webp">/, "OpenGraph image"],
  [/<meta property="og:image:width" content="1200">/, "OpenGraph image width"],
  [/<meta property="og:image:height" content="630">/, "OpenGraph image height"],
  [/<meta name="twitter:card" content="summary_large_image">/, "Twitter card"],
  [/<script type="application\/ld\+json">\{/, "JSON-LD"],
  [/data-theme-bootstrap/, "pre-paint theme bootstrap"],
  [/value="light" data-theme-choice/, "light theme choice"],
  [/value="dark" data-theme-choice/, "dark theme choice"],
  [/value="system" data-theme-choice/, "system theme choice"],
  [
    /<svg\b(?=[^>]*data-hero-brand)(?=[^>]*viewBox="0 0 370 152")(?=[^>]*width="370")(?=[^>]*height="152")(?=[^>]*aria-hidden="true")[^>]*>/,
    "intrinsic-size inline animated Saltacode lockup",
  ],
  [/>SaltaCode<\/text>/, "vector brand name"],
  [/>Innovación y Desarrollo<\/text>/, "vector brand tagline"],
  [/data-hero-motion aria-hidden="true"/, "decorative hero motion surface"],
  [/Escribí tu consulta para nuestro agente/, "agent-first hero prompt"],
  [/Nuestro agente IA responderá al instante/, "agent assistance explanation"],
  [/href="mailto:saltacodear@gmail\.com"/, "email contact path"],
  [/href="https:\/\/wa\.me\/5493875296587/, "WhatsApp contact path"],
];

for (const [pattern, label] of assertions) {
  if (!pattern.test(index)) {
    throw new Error(`Missing required build output: ${label}`);
  }
}

if (
  !emittedCss.includes(
    ".hero-brand-draw,.hero-brand-copy{opacity:1;stroke-dashoffset:0;animation:none}",
  )
) {
  throw new Error("The animated brand lockup must expose a static reduced-motion state.");
}

const themeImages = [...index.matchAll(/<img\b(?=[^>]*\bdata-theme-image\b)[^>]*>/g)];
if (themeImages.length !== EXPECTED_CLIENTS.length + 2) {
  throw new Error("Homepage theme images must include every client logo and the header/footer brand marks.");
}
for (const [image] of themeImages) {
  if (!/\bdata-theme-src-light="\/_astro\/[^"]+"/.test(image) ||
      !/\bdata-theme-src-dark="\/_astro\/[^"]+"/.test(image)) {
    throw new Error("Every theme image must provide optimized light and dark sources.");
  }
}

verifySharedNavigation(index, "", "Homepage");
verifySharedNavigation(notFound, "/", "404 page");

const homeHeader = extractLandmark(index, "header");
const notFoundHeader = extractLandmark(notFound, "header");
if (!/<header\b[^>]*\bdata-scroll-header(?:\s|>)/.test(homeHeader)) {
  throw new Error("The homepage header must opt into scroll reveal behavior.");
}
if (/\bdata-scroll-header(?:\s|>)/.test(notFoundHeader)) {
  throw new Error("The 404 recovery header must remain visible without scroll reveal behavior.");
}

const notFoundLocalFragmentLinks = extractAnchorHrefs(notFound).filter((href) => href.startsWith("#"));
if (
  notFoundLocalFragmentLinks.length !== 1 ||
  notFoundLocalFragmentLinks[0] !== "#contenido" ||
  !hasId(notFound, "contenido")
) {
  throw new Error("The 404 page skip link must be the only local fragment link and target #contenido.");
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

const legacyFragmentAliases = [
  ["productsAndServices", "servicios", "section"],
  ["it-consulting", "consultoria-it", "article"],
  ["saas-solutions", "soluciones-saas", "article"],
  ["ourCustomers", "clientes", "section"],
  ["aboutUs", "nosotros", "section"],
  ["footer", "contacto", "section"],
];

for (const [alias, target, element] of legacyFragmentAliases) {
  const aliasTags = index.match(new RegExp(`<span\\b[^>]*\\bid="${alias}"[^>]*>\\s*</span>`, "g")) ?? [];
  if (aliasTags.length !== 1) {
    throw new Error(`Legacy fragment #${alias} must have exactly one neutral alias target.`);
  }

  const aliasTag = aliasTags[0];
  if (!/class="legacy-fragment-alias"/.test(aliasTag) || !/aria-hidden="true"/.test(aliasTag)) {
    throw new Error(`Legacy fragment #${alias} must be hidden from assistive technology.`);
  }
  if (/\b(?:href|tabindex)=/.test(aliasTag)) {
    throw new Error(`Legacy fragment #${alias} must not be interactive or focusable.`);
  }

  const mappedTarget = new RegExp(
    `<${element}\\b[^>]*\\bid="${target}"[^>]*>\\s*<span\\b[^>]*\\bid="${alias}"`,
  );
  if (!mappedTarget.test(index)) {
    throw new Error(`Legacy fragment #${alias} is not mapped to #${target}.`);
  }
}

if (!/<h2 id="clients-title">Nuestros clientes<\/h2>/.test(index)) {
  throw new Error("The clients heading must use the conservative historical wording.");
}

const clientList = index.match(/<ul class="container client-list"[^>]*>([\s\S]*?)<\/ul>/)?.[1];
if (!clientList) {
  throw new Error("The rendered client list is missing.");
}

const clientImageTags = [...clientList.matchAll(/<img\b[^>]*>/g)].map((match) => match[0]);
const renderedClientNames = clientImageTags.map((tag) =>
  (attributeValue(tag, "alt") ?? "").replace(/^Logo de /, ""),
);
if (JSON.stringify(renderedClientNames) !== JSON.stringify(EXPECTED_CLIENTS)) {
  throw new Error(`Unexpected client set or order: ${renderedClientNames.join(", ")}.`);
}

for (const tag of clientImageTags) {
  if (
    attributeValue(tag, "loading") !== "lazy" ||
    attributeValue(tag, "decoding") !== "async" ||
    attributeValue(tag, "width") !== "180" ||
    attributeValue(tag, "height") !== "80"
  ) {
    throw new Error(`Client logo does not preserve lazy-loading and intrinsic dimensions: ${tag}`);
  }
}

if (assetManifest.schemaVersion !== 1 || assetManifest.assets?.length !== 13) {
  throw new Error("The theme-ready image manifest must contain the two brand and eight client assets.");
}

let totalAssetVariantBytes = 0;
for (const asset of assetManifest.assets) {
  const expectedCanvas = asset.kind === "client"
    ? { width: 360, height: 160 }
    : asset.id === "brand-mark"
      ? { width: 256, height: 256 }
      : { width: 720, height: 288 };

  if (
    asset.canvas?.width !== expectedCanvas.width ||
    asset.canvas?.height !== expectedCanvas.height ||
    !asset.variants?.onLight ||
    !asset.variants?.onDark
  ) {
    throw new Error(`Asset ${asset.id} does not satisfy the theme surface contract.`);
  }

  for (const variant of Object.values(asset.variants)) {
    totalAssetVariantBytes += variant.output.bytes;
    if (variant.output.bytes > ASSET_LIBRARY_BUDGETS.maximumVariantBytes) {
      throw new Error(`Asset ${variant.output.path} exceeds the per-variant image budget.`);
    }
  }
}

console.log(
  `Asset budget: ${totalAssetVariantBytes} bytes / ${ASSET_LIBRARY_BUDGETS.totalVariantBytes} bytes maximum for 26 variants.`,
);
if (totalAssetVariantBytes > ASSET_LIBRARY_BUDGETS.totalVariantBytes) {
  throw new Error("The complete theme-ready image library exceeds its performance budget.");
}

if (!robots.includes("Allow: /") || !robots.includes("https://saltacode.com.ar/sitemap.xml")) {
  throw new Error("robots.txt does not expose the production sitemap.");
}

if (!sitemap.includes("<loc>https://saltacode.com.ar/</loc>")) {
  throw new Error("sitemap.xml does not contain the canonical home URL.");
}

if (homeExecutableScripts.length !== 3) {
  throw new Error("The homepage must ship only the theme bootstrap, page shell, and deferred hero loader.");
}

const externalModuleScripts = homeExecutableScripts.filter((script) => /\bsrc=/.test(script[1]));
const inlineScripts = homeExecutableScripts.filter((script) => !/\bsrc=/.test(script[1]));
if (externalModuleScripts.length !== 1 || inlineScripts.length !== 2) {
  throw new Error("The homepage script split must remain one external hero loader plus two CSP-hashed controllers.");
}

const [, heroScriptAttributes, heroScriptSource] = externalModuleScripts[0];
if (
  !/\btype="module"/.test(heroScriptAttributes) ||
  !/\bsrc="\/_astro\/[^\"]+\.js"/.test(heroScriptAttributes) ||
  heroScriptSource.trim() !== ""
) {
  throw new Error("The hero animation loader must remain one fingerprinted ES module.");
}

const themeBootstrap = inlineScripts.find((script) => /\bdata-theme-bootstrap\b/.test(script[1]));
const pageShell = inlineScripts.find((script) => /\btype="module"/.test(script[1]));
if (!themeBootstrap || !pageShell || themeBootstrap[2].trim() === "") {
  throw new Error("The theme bootstrap and shared page shell must both remain inline.");
}

const [, pageShellAttributes, pageShellSource] = pageShell;
if (
  !/\btype="module"/.test(pageShellAttributes) ||
  /\bsrc=/.test(pageShellAttributes) ||
  pageShellSource.trim() === ""
) {
  throw new Error("The theme and scroll controller must be one inline ES module.");
}

const notFoundExecutableScripts = extractExecutableScripts(notFound);
if (
  notFoundExecutableScripts.length !== 2 ||
  !notFoundExecutableScripts.some((script) => /\bdata-theme-bootstrap\b/.test(script[1])) ||
  !notFoundExecutableScripts.some((script) => /\btype="module"/.test(script[1])) ||
  notFoundExecutableScripts.some((script) => /\bsrc=/.test(script[1]))
) {
  throw new Error("The 404 route must ship only the CSP-hashed theme bootstrap and page shell.");
}

console.log(
  `Verified ${buildFiles.length} emitted files, static HTML, canonical metadata, crawl files, contacts, and local build budgets.`,
);
