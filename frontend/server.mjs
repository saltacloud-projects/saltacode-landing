import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { readFile, stat } from "node:fs/promises";
import { createServer } from "node:http";
import { extname, resolve, sep } from "node:path";
import { pipeline } from "node:stream/promises";
import { fileURLToPath } from "node:url";
import { createGzip } from "node:zlib";

const port = Number.parseInt(process.env.PORT ?? "8080", 10);
const host = process.env.HOST ?? "0.0.0.0";
const moduleDirectory = fileURLToPath(new URL(".", import.meta.url));
const staticRoot = resolve(process.env.STATIC_ROOT ?? resolve(moduleDirectory, "dist"));

function inlineExecutableSources(markup) {
  return [...markup.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)]
    .filter(([, attributes]) => {
      return !/\bsrc=/.test(attributes) && !/\btype="application\/ld\+json"/.test(attributes);
    })
    .map((match) => match[2]);
}

const staticPageMarkup = await Promise.all(
  ["index.html", "404.html"].map((file) => readFile(resolve(staticRoot, file), "utf8")),
);
const inlineScriptHashes = [
  ...new Set(
    staticPageMarkup
      .flatMap(inlineExecutableSources)
      .map((source) => createHash("sha256").update(source).digest("base64")),
  ),
];
if (inlineScriptHashes.length === 0) {
  throw new Error("Static pages must contain a CSP-hashed theme bootstrap.");
}

if (!Number.isInteger(port) || port < 1 || port > 65535) {
  throw new Error("PORT must be an integer between 1 and 65535.");
}

const mimeTypes = new Map([
  [".avif", "image/avif"],
  [".css", "text/css; charset=utf-8"],
  [".gif", "image/gif"],
  [".html", "text/html; charset=utf-8"],
  [".ico", "image/x-icon"],
  [".jpg", "image/jpeg"],
  [".jpeg", "image/jpeg"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".png", "image/png"],
  [".svg", "image/svg+xml; charset=utf-8"],
  [".txt", "text/plain; charset=utf-8"],
  [".webp", "image/webp"],
  [".xml", "application/xml; charset=utf-8"],
]);

const compressibleExtensions = new Set([".css", ".html", ".js", ".json", ".svg", ".txt", ".xml"]);

const contentSecurityPolicy = [
  "default-src 'self'",
  "base-uri 'self'",
  "connect-src 'self'",
  "font-src 'self'",
  "form-action 'self' mailto: https://wa.me",
  "frame-ancestors 'none'",
  "img-src 'self' data:",
  "object-src 'none'",
  `script-src 'self' ${inlineScriptHashes.map((hash) => `'sha256-${hash}'`).join(" ")}`,
  "style-src 'self'",
];

const securityHeaders = {
  "Permissions-Policy": "accelerometer=(), camera=(), geolocation=(), gyroscope=(), microphone=(), payment=(), usb=()",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};

function requestUsesForwardedHttps(request) {
  const forwardedProto = request.headers["x-forwarded-proto"];
  const value = Array.isArray(forwardedProto) ? forwardedProto[0] : forwardedProto;
  return value?.split(",", 1)[0].trim().toLowerCase() === "https";
}

function setSecurityHeaders(request, response) {
  const policy = requestUsesForwardedHttps(request)
    ? [...contentSecurityPolicy, "upgrade-insecure-requests"]
    : contentSecurityPolicy;
  response.setHeader("Content-Security-Policy", policy.join("; "));
  for (const [name, value] of Object.entries(securityHeaders)) {
    response.setHeader(name, value);
  }
}

function cacheControl(pathname, extension) {
  if (pathname.startsWith("/_astro/")) {
    return "public, max-age=31536000, immutable";
  }

  if (extension === ".html" || pathname === "/robots.txt" || pathname === "/sitemap.xml") {
    return "public, max-age=0, must-revalidate";
  }

  return "public, max-age=3600, stale-while-revalidate=86400";
}

async function resolveRequestPath(pathname) {
  let relativePath = pathname;

  if (relativePath === "/") {
    relativePath = "/index.html";
  } else if (relativePath.endsWith("/")) {
    relativePath = `${relativePath}index.html`;
  }

  const candidate = resolve(staticRoot, `.${relativePath}`);
  if (candidate !== staticRoot && !candidate.startsWith(`${staticRoot}${sep}`)) {
    return null;
  }

  try {
    const fileStat = await stat(candidate);
    return fileStat.isFile() ? { filePath: candidate, fileStat } : null;
  } catch {
    return null;
  }
}

function sendBody(request, response, body) {
  response.setHeader("Content-Length", Buffer.byteLength(body));
  response.end(request.method === "HEAD" ? undefined : body);
}

function acceptsGzip(request) {
  const header = request.headers["accept-encoding"];
  const value = Array.isArray(header) ? header.join(",") : (header ?? "");

  return value.split(",").some((entry) => {
    const [coding, ...parameters] = entry.trim().toLowerCase().split(";");
    if (coding !== "gzip") return false;
    const quality = parameters
      .map((parameter) => parameter.trim().match(/^q=(\d(?:\.\d+)?)$/)?.[1])
      .find(Boolean);
    return quality === undefined || Number(quality) > 0;
  });
}

async function sendFile(request, response, filePath, fileSize, extension) {
  const compress =
    fileSize >= 1_024 && compressibleExtensions.has(extension) && acceptsGzip(request);

  if (compressibleExtensions.has(extension)) response.setHeader("Vary", "Accept-Encoding");
  if (compress) response.setHeader("Content-Encoding", "gzip");
  else response.setHeader("Content-Length", fileSize);

  if (request.method === "HEAD") {
    response.end();
    return;
  }

  if (compress) {
    await pipeline(createReadStream(filePath), createGzip({ level: 6 }), response);
    return;
  }

  await pipeline(createReadStream(filePath), response);
}

async function sendNotFound(request, response) {
  const fallback = await resolveRequestPath("/404.html");
  response.statusCode = 404;
  response.setHeader("Cache-Control", "public, max-age=0, must-revalidate");

  if (!fallback) {
    response.setHeader("Content-Type", "text/plain; charset=utf-8");
    sendBody(request, response, "Not Found\n");
    return;
  }

  response.setHeader("Content-Type", "text/html; charset=utf-8");
  await sendFile(request, response, fallback.filePath, fallback.fileStat.size, ".html");
}

async function handleRequest(request, response) {
  setSecurityHeaders(request, response);

  if (request.method !== "GET" && request.method !== "HEAD") {
    response.statusCode = 405;
    response.setHeader("Allow", "GET, HEAD");
    response.setHeader("Content-Type", "text/plain; charset=utf-8");
    sendBody(request, response, "Method Not Allowed\n");
    return;
  }

  let requestUrl;
  let pathname;
  try {
    requestUrl = new URL(request.url ?? "/", "http://localhost");
    pathname = decodeURIComponent(requestUrl.pathname);
  } catch {
    response.statusCode = 400;
    response.setHeader("Content-Type", "text/plain; charset=utf-8");
    sendBody(request, response, "Bad Request\n");
    return;
  }

  if (pathname === "/index.html") {
    response.statusCode = 301;
    response.setHeader("Cache-Control", "public, max-age=3600");
    response.setHeader("Location", `/${requestUrl.search}`);
    response.end();
    return;
  }

  if (pathname === "/healthz") {
    response.statusCode = 200;
    response.setHeader("Cache-Control", "no-store");
    response.setHeader("Content-Type", "application/json; charset=utf-8");
    sendBody(request, response, '{"status":"ok"}\n');
    return;
  }

  const asset = await resolveRequestPath(pathname);
  if (!asset) {
    await sendNotFound(request, response);
    return;
  }

  const extension = extname(asset.filePath).toLowerCase();
  const lastModified = asset.fileStat.mtime.toUTCString();
  response.setHeader("Cache-Control", cacheControl(pathname, extension));
  response.setHeader("Content-Type", mimeTypes.get(extension) ?? "application/octet-stream");
  response.setHeader("Last-Modified", lastModified);
  if (compressibleExtensions.has(extension)) response.setHeader("Vary", "Accept-Encoding");

  if (request.headers["if-modified-since"] === lastModified) {
    response.statusCode = 304;
    response.removeHeader("Content-Length");
    response.end();
    return;
  }

  response.statusCode = 200;
  await sendFile(request, response, asset.filePath, asset.fileStat.size, extension);
}

const server = createServer((request, response) => {
  handleRequest(request, response).catch((error) => {
    console.error(error);
    if (!response.headersSent) {
      setSecurityHeaders(response);
      response.statusCode = 500;
      response.setHeader("Cache-Control", "no-store");
      response.setHeader("Content-Type", "text/plain; charset=utf-8");
      sendBody(request, response, "Internal Server Error\n");
    } else {
      response.destroy();
    }
  });
});

server.listen(port, host, () => {
  console.log(`Saltacode frontend listening on http://${host}:${port}`);
});

function shutdown(signal) {
  console.log(`Received ${signal}; shutting down.`);
  server.close((error) => {
    process.exit(error ? 1 : 0);
  });
}

process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));
