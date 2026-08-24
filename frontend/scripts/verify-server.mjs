import { spawn } from "node:child_process";
import { readdir } from "node:fs/promises";
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
  if (home.headers.get("cache-control") !== "public, max-age=0, must-revalidate") {
    throw new Error("HTML revalidation policy is missing.");
  }
  if (!home.headers.get("content-security-policy")?.includes("frame-ancestors 'none'")) {
    throw new Error("Security headers are missing from the home page.");
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

  const missing = await fetch(`${baseUrl}/definitely-missing`);
  if (missing.status !== 404 || !(await missing.text()).includes("Página no encontrada")) {
    throw new Error("Unknown routes must return the branded 404 page with status 404.");
  }

  const api = await fetch(`${baseUrl}/api/chat`);
  if (api.status !== 404) {
    throw new Error("The frontend must not proxy or fall back for /api routes.");
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

  const head = await fetch(`${baseUrl}/`, { method: "HEAD" });
  if (head.status !== 200 || (await head.text()) !== "") {
    throw new Error("HEAD requests must return headers without a body.");
  }

  console.log("Verified health, index redirect, real 404s, no API fallback, cache policy, security headers, and HEAD support.");
} finally {
  child.kill("SIGTERM");
  await new Promise((resolveExit) => {
    child.once("exit", resolveExit);
    setTimeout(resolveExit, 1_000).unref();
  });
}
