import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { readdir } from "node:fs/promises";
import { request as httpRequest } from "node:http";
import { createServer } from "node:net";
import { resolve } from "node:path";

async function availablePort() {
  return new Promise((resolvePort, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        reject(new Error("Could not allocate a test port."));
        return;
      }
      server.close(() => resolvePort(address.port));
    });
  });
}

const port = await availablePort();
const root = resolve(import.meta.dirname, "..");
const child = spawn(process.execPath, [resolve(root, "server.mjs")], {
  cwd: root,
  env: { ...process.env, HOST: "127.0.0.1", PORT: String(port) },
  stdio: ["ignore", "pipe", "pipe"],
});

let output = "";
child.stdout.on("data", (chunk) => { output += chunk; });
child.stderr.on("data", (chunk) => { output += chunk; });

const baseUrl = `http://127.0.0.1:${port}`;

async function requestServer(path, { method = "GET", headers = {} } = {}) {
  return new Promise((resolveRequest, rejectRequest) => {
    const request = httpRequest(
      { hostname: "127.0.0.1", port, path, method, headers },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(chunk));
        response.on("end", () => {
          const responseHeaders = new Headers(
            Object.entries(response.headers)
              .filter((entry) => entry[1] !== undefined)
              .map(([name, value]) => [name, Array.isArray(value) ? value.join(", ") : value]),
          );
          resolveRequest({
            status: response.statusCode ?? 0,
            headers: responseHeaders,
            text: Buffer.concat(chunks).toString("utf8"),
          });
        });
      },
    );
    request.once("error", rejectRequest);
    request.end();
  });
}

async function waitForServer() {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      const response = await fetch(`${baseUrl}/healthz`);
      if (response.ok) return;
    } catch {
      // The child may still be starting.
    }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 50));
  }
  throw new Error(`Static server did not start.\n${output}`);
}

try {
  await waitForServer();

  const home = await fetch(`${baseUrl}/`);
  if (home.status !== 200 || !home.headers.get("content-type")?.startsWith("text/html")) {
    throw new Error("Home page was not served as HTML with status 200.");
  }
  if (home.headers.get("cache-control") !== "public, max-age=0, must-revalidate, no-transform") {
    throw new Error("HTML must retain revalidation while preventing intermediary transformations.");
  }
  if (
    home.headers.get("content-encoding") !== "gzip" ||
    !home.headers.get("vary")?.includes("Accept-Encoding")
  ) {
    throw new Error("Compressible HTML must negotiate gzip and vary by content encoding.");
  }
  const contentSecurityPolicy = home.headers.get("content-security-policy") ?? "";
  if (contentSecurityPolicy.includes("upgrade-insecure-requests")) {
    throw new Error("Direct HTTP previews must not upgrade same-origin static assets to HTTPS.");
  }
  const homeMarkup = await home.text();
  if (!homeMarkup.includes('id="useful-links"') || !homeMarkup.includes('id="social-links"')) {
    throw new Error("The footer must preserve the historical useful-links and social-links fragments.");
  }
  const executableScripts = [
    ...homeMarkup.matchAll(/<script\b(?![^>]*type="application\/ld\+json")([^>]*)>([\s\S]*?)<\/script>/g),
  ];
  const inlineScripts = executableScripts.filter((script) => !/\bsrc=/.test(script[1]));
  if (inlineScripts.length === 0 || !homeMarkup.includes("data-theme-bootstrap")) {
    throw new Error("The home page does not contain its pre-paint theme bootstrap.");
  }
  const expectedScriptHashes = inlineScripts.map((script) => {
    return createHash("sha256").update(script[2]).digest("base64");
  });
  const externalModuleSources = executableScripts
    .map((script) => script[1].match(/\bsrc="([^"]+)"/)?.[1])
    .filter(Boolean);
  if (externalModuleSources.length === 0) {
    throw new Error("The home page does not contain its interactive module controllers.");
  }
  if (
    !contentSecurityPolicy.includes("frame-ancestors 'none'") ||
    !expectedScriptHashes.every((hash) => contentSecurityPolicy.includes(`'sha256-${hash}'`)) ||
    contentSecurityPolicy.includes("'unsafe-inline'") ||
    contentSecurityPolicy.includes("'unsafe-eval'")
  ) {
    throw new Error("Security headers are missing from the home page.");
  }

  const localForwardedHttps = await fetch(`${baseUrl}/`, {
    method: "HEAD",
    headers: { "X-Forwarded-Proto": "https" },
  });
  if (
    localForwardedHttps.status !== 200 ||
    localForwardedHttps.headers.has("strict-transport-security") ||
    localForwardedHttps.headers
      .get("content-security-policy")
      ?.includes("upgrade-insecure-requests")
  ) {
    throw new Error("Forwarded headers must not turn localhost previews into production HTTPS responses.");
  }

  const canonicalQuery = "utm_source=cutover&encoded=%2B%2F%3F&repeat=one&repeat=two";
  for (const [host, protocol, expectedStatus] of [
    ["saltacode.com.ar", "http", 308],
    ["www.saltacode.com.ar", "http", 308],
    ["www.saltacode.com.ar", "https", 308],
    ["saltacode.com.ar", "https", 200],
  ]) {
    const productionResponse = await requestServer(`/servicios/?${canonicalQuery}`, {
      method: "HEAD",
      headers: { Host: host, "X-Forwarded-Proto": protocol },
    });
    if (productionResponse.status !== expectedStatus) {
      throw new Error(`${protocol}://${host} returned ${productionResponse.status}; expected ${expectedStatus}.`);
    }
    if (expectedStatus === 308) {
      const expectedLocation = `https://saltacode.com.ar/servicios/?${canonicalQuery}`;
      if (productionResponse.headers.get("location") !== expectedLocation) {
        throw new Error(`${protocol}://${host} did not preserve path and query in its canonical redirect.`);
      }
      if (protocol === "http" && productionResponse.headers.has("strict-transport-security")) {
        throw new Error("HTTP-origin redirects must not emit HSTS.");
      }
    } else if (
      productionResponse.headers.get("strict-transport-security") !==
        "max-age=31536000" ||
      !productionResponse.headers
        .get("content-security-policy")
        ?.includes("upgrade-insecure-requests")
    ) {
      throw new Error("Verified production HTTPS responses must emit HSTS and the CSP upgrade directive.");
    }
  }

  const localReview = await requestServer(`/servicios/?${canonicalQuery}`, {
    method: "HEAD",
    headers: { Host: "127.0.0.1", "X-Forwarded-Proto": "http" },
  });
  if (localReview.status !== 200 || localReview.headers.has("strict-transport-security")) {
    throw new Error("The loopback review origin must not be redirected or receive HSTS.");
  }

  for (const protocol of ["http", "https"]) {
    const health = await requestServer("/healthz", {
      method: "HEAD",
      headers: { Host: "www.saltacode.com.ar", "X-Forwarded-Proto": protocol },
    });
    if (health.status !== 200 || health.headers.has("location")) {
      throw new Error("Health checks must stay local and must not follow canonical-host redirects.");
    }
  }

  const ambiguousForwarding = await requestServer("/", {
    method: "HEAD",
    headers: { Host: "saltacode.com.ar", "X-Forwarded-Proto": "https, http" },
  });
  if (ambiguousForwarding.status !== 200 || ambiguousForwarding.headers.has("strict-transport-security")) {
    throw new Error("Ambiguous proxy protocol chains must not be trusted for HSTS or redirects.");
  }

  for (const externalModuleSource of externalModuleSources) {
    const externalModule = await fetch(`${baseUrl}${externalModuleSource}`);
    if (
      externalModule.status !== 200 ||
      !externalModule.headers.get("content-type")?.startsWith("text/javascript")
    ) {
      throw new Error(`The fingerprinted controller ${externalModuleSource} is not served as JavaScript.`);
    }
  }

  const publicRoutes = [
    "/servicios/",
    "/servicios/software-a-medida/",
    "/servicios/consultoria-it/",
    "/servicios/equipos-it/",
    "/servicios/productos-saas/",
    "/nosotros/",
    "/contacto/",
    "/legal/privacidad/",
    "/legal/cookies/",
    "/legal/terminos/",
  ];
  for (const route of publicRoutes) {
    const page = await fetch(`${baseUrl}${route}`);
    const markup = await page.text();
    if (page.status !== 200 || !page.headers.get("content-type")?.startsWith("text/html")) {
      throw new Error(`${route} was not served as HTML with status 200.`);
    }
    if (page.headers.get("cache-control") !== "public, max-age=0, must-revalidate, no-transform") {
      throw new Error(`${route} lost the origin-integrity cache policy.`);
    }
    if ((markup.match(/<h1(?:\s|>)/g) ?? []).length !== 1 || !markup.includes("class=\"breadcrumbs\"")) {
      throw new Error(`${route} lost its static h1 or visible breadcrumbs.`);
    }
    if (route === "/contacto/" && !markup.includes('href="mailto:')) {
      throw new Error("The contact page must retain its static email link at the origin.");
    }
    const policy = page.headers.get("content-security-policy") ?? "";
    const inline = [...markup.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)].filter(
      (script) => !/\bsrc=/.test(script[1]) && !/\btype="application\/ld\+json"/.test(script[1]),
    );
    if (!inline.every((script) => policy.includes(`'sha256-${createHash("sha256").update(script[2]).digest("base64")}'`))) {
      throw new Error(`${route} contains an inline script missing from the generated CSP.`);
    }
  }

  const legacyQuery = "utm_source=legacy&encoded=%2B%2F%3F&space=one+two&empty=&repeat=one&repeat=two";
  for (const method of ["GET", "HEAD"]) {
    const legacyIndex = await fetch(`${baseUrl}/index.html?${legacyQuery}`, {
      method,
      redirect: "manual",
    });
    if (legacyIndex.status !== 301 || legacyIndex.headers.get("location") !== `/?${legacyQuery}`) {
      throw new Error(`${method} /index.html must permanently redirect to / and preserve its query string.`);
    }
    if ((await legacyIndex.text()) !== "") {
      throw new Error(`${method} /index.html redirect must not return a response body.`);
    }
  }

  for (const [legacyPath, canonicalPath] of [
    ["/servicios", "/servicios/"],
    ["/servicios/index.html", "/servicios/"],
    ["/servicios/software-a-medida", "/servicios/software-a-medida/"],
    ["/legal/privacidad", "/legal/privacidad/"],
    ["/legal/privacidad/index.html", "/legal/privacidad/"],
  ]) {
    const redirect = await fetch(`${baseUrl}${legacyPath}?${legacyQuery}`, { redirect: "manual" });
    if (redirect.status !== 301 || redirect.headers.get("location") !== `${canonicalPath}?${legacyQuery}`) {
      throw new Error(`${legacyPath} must redirect to ${canonicalPath} and preserve its query string.`);
    }
  }

  const missing = await fetch(`${baseUrl}/definitely-missing`);
  const missingMarkup = await missing.text();
  if (missing.status !== 404 || !missingMarkup.includes("Página no encontrada")) {
    throw new Error("Unknown routes must return the branded 404 page with status 404.");
  }
  if (missing.headers.get("cache-control") !== "public, max-age=0, must-revalidate, no-transform") {
    throw new Error("Branded HTML error responses must prevent intermediary transformations.");
  }
  const missingCsp = missing.headers.get("content-security-policy") ?? "";
  const missingInlineScripts = [
    ...missingMarkup.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g),
  ].filter((script) => {
    return !/\bsrc=/.test(script[1]) && !/\btype="application\/ld\+json"/.test(script[1]);
  });
  if (
    missingInlineScripts.length === 0 ||
    !missingInlineScripts.every((script) => {
      const hash = createHash("sha256").update(script[2]).digest("base64");
      return missingCsp.includes(`'sha256-${hash}'`);
    })
  ) {
    throw new Error("The branded 404 theme bootstrap is not covered by CSP hashes.");
  }

  const api = await fetch(`${baseUrl}/api/chat`);
  const apiProblem = await api.json();
  if (
    api.status !== 503 ||
    !api.headers.get("content-type")?.startsWith("application/problem+json") ||
    api.headers.get("cache-control") !== "no-store" ||
    apiProblem.code !== "backend_unavailable"
  ) {
    throw new Error("Unconfigured API proxy requests must fail closed with a safe problem response.");
  }

  const robots = await fetch(`${baseUrl}/robots.txt`);
  if (robots.status !== 200 || robots.headers.get("cache-control") !== "public, max-age=0, must-revalidate") {
    throw new Error("robots.txt must be served with revalidation.");
  }

  const astroAssets = await readdir(resolve(root, "dist/_astro"));
  const assetName = astroAssets.find((name) => /\.(?:css|js|avif|webp)$/.test(name));
  if (!assetName) {
    throw new Error("No fingerprinted Astro asset was generated.");
  }
  const asset = await fetch(`${baseUrl}/_astro/${assetName}`);
  if (asset.headers.get("cache-control") !== "public, max-age=31536000, immutable") {
    throw new Error("Fingerprint assets must be served with immutable caching.");
  }

  const iconSprite = await fetch(`${baseUrl}/icons/site-icons.svg`);
  if (iconSprite.status !== 200 || !iconSprite.headers.get("content-type")?.startsWith("image/svg+xml")) {
    throw new Error("The standardized channel icon sprite is not served as SVG.");
  }

  const animatedLockupName = astroAssets.find((name) =>
    /^animated-lockup-on(?:Light|Dark)\..+\.svg$/.test(name),
  );
  if (!animatedLockupName) {
    throw new Error("The exact animated Saltacode lockup was not emitted.");
  }
  const animatedLockup = await fetch(`${baseUrl}/_astro/${animatedLockupName}`);
  if (
    animatedLockup.headers.get("content-encoding") !== "gzip" ||
    !animatedLockup.headers.get("vary")?.includes("Accept-Encoding")
  ) {
    throw new Error("The animated SVG lockup must be served with negotiated gzip compression.");
  }

  const head = await fetch(`${baseUrl}/`, { method: "HEAD" });
  if (head.status !== 200 || (await head.text()) !== "") {
    throw new Error("HEAD requests must return headers without a body.");
  }

  console.log("Verified health, compression, nested-route redirects, all public pages, CSP hashes, real 404s, fail-closed API proxy, cache policy, security headers, and HEAD support.");
} finally {
  child.kill("SIGTERM");
  await new Promise((resolveExit) => {
    child.once("exit", resolveExit);
    setTimeout(resolveExit, 1_000).unref();
  });
}
