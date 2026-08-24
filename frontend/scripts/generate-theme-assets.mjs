import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { dirname, relative, resolve } from "node:path";

import sharp from "sharp";

const frontendRoot = resolve(import.meta.dirname, "..");
const outputRoot = resolve(frontendRoot, "src/assets/optimized");
const manifestPath = resolve(outputRoot, "manifest.json");
const checkOnly = process.argv.includes("--check");

const clientCanvas = Object.freeze({ width: 360, height: 160, maxWidth: 320, maxHeight: 120 });

const assets = [
  {
    id: "brand-mark",
    kind: "brand",
    canvas: { width: 256, height: 256, maxWidth: 224, maxHeight: 224 },
    variants: {
      onLight: { source: "src/assets/brand/logo_nav_light.png" },
      onDark: { source: "src/assets/brand/logo_nav_dark.png" },
    },
  },
  {
    id: "brand-lockup",
    kind: "brand",
    canvas: { width: 720, height: 288, maxWidth: 640, maxHeight: 224 },
    variants: {
      onLight: { source: "src/assets/brand/imagotipo_light.png" },
      onDark: { source: "src/assets/brand/imagotipo_dark.png" },
    },
  },
  ...[
    ["ko27", "src/assets/clients/ko27.png"],
    ["balance", "src/assets/clients/balance.png"],
    ["v8", "src/assets/clients/v8.png"],
    ["grupo-kamal", "src/assets/clients/kamal.png"],
    ["planeta-puna", "src/assets/clients/puna.png"],
    ["optica-total", "src/assets/clients/optica-total.png"],
  ].map(([slug, source]) => ({
    id: `client-${slug}`,
    kind: "client",
    canvas: clientCanvas,
    variants: {
      onLight: { source, color: "#74747D" },
      onDark: { source, color: "#D8D8E0" },
    },
  })),
  {
    id: "client-metalnor",
    kind: "client",
    canvas: clientCanvas,
    variants: {
      onLight: { source: "src/assets/clients/metalnor-on-light.png" },
      onDark: { source: "src/assets/clients/metalnor-on-dark.webp" },
    },
  },
  {
    id: "client-cocel",
    kind: "client",
    canvas: clientCanvas,
    variants: {
      onLight: { source: "src/assets/clients/cocel-on-light.png" },
      onDark: { source: "src/assets/clients/cocel-on-dark.png" },
    },
  },
];

function sha256(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

function outputPath(asset, theme) {
  return resolve(outputRoot, asset.kind, `${asset.id.replace(`${asset.kind}-`, "")}-${theme}.webp`);
}

async function renderVariant(asset, variant) {
  const sourcePath = resolve(frontendRoot, variant.source);
  const sourceBuffer = await readFile(sourcePath);
  const trimmed = await sharp(sourceBuffer)
    .ensureAlpha()
    .trim({ background: { r: 0, g: 0, b: 0, alpha: 0 }, threshold: 8 })
    .png()
    .toBuffer({ resolveWithObject: true });
  const resized = await sharp(trimmed.data)
    .resize({
      width: asset.canvas.maxWidth,
      height: asset.canvas.maxHeight,
      fit: "inside",
      kernel: sharp.kernel.lanczos3,
      withoutEnlargement: false,
    })
    .png()
    .toBuffer({ resolveWithObject: true });

  const foreground = variant.color
    ? await sharp({
        create: {
          width: resized.info.width,
          height: resized.info.height,
          channels: 4,
          background: variant.color,
        },
      })
        .composite([{ input: resized.data, blend: "dest-in" }])
        .png()
        .toBuffer()
    : resized.data;

  const left = Math.round((asset.canvas.width - resized.info.width) / 2);
  const top = Math.round((asset.canvas.height - resized.info.height) / 2);
  const output = await sharp({
    create: {
      width: asset.canvas.width,
      height: asset.canvas.height,
      channels: 4,
      background: { r: 0, g: 0, b: 0, alpha: 0 },
    },
  })
    .composite([{ input: foreground, left, top }])
    .webp({ lossless: true, effort: 6, alphaQuality: 100 })
    .toBuffer();

  return {
    output,
    source: {
      path: variant.source,
      bytes: sourceBuffer.byteLength,
      sha256: sha256(sourceBuffer),
      width: trimmed.info.width,
      height: trimmed.info.height,
    },
  };
}

const expectedOutputs = new Set();
const manifestAssets = [];
const drift = [];

for (const asset of assets) {
  const manifestVariants = {};
  for (const [theme, variant] of Object.entries(asset.variants)) {
    const target = outputPath(asset, theme);
    const rendered = await renderVariant(asset, variant);
    const targetRelative = relative(frontendRoot, target);
    expectedOutputs.add(target);
    manifestVariants[theme] = {
      source: rendered.source,
      output: {
        path: targetRelative,
        bytes: rendered.output.byteLength,
        sha256: sha256(rendered.output),
        width: asset.canvas.width,
        height: asset.canvas.height,
      },
    };

    if (checkOnly) {
      const current = await readFile(target).catch(() => null);
      if (!current || !current.equals(rendered.output)) drift.push(targetRelative);
    } else {
      await mkdir(dirname(target), { recursive: true });
      await writeFile(target, rendered.output);
    }
  }

  manifestAssets.push({
    id: asset.id,
    kind: asset.kind,
    canvas: { width: asset.canvas.width, height: asset.canvas.height },
    variants: manifestVariants,
  });
}

const manifest = `${JSON.stringify(
  {
    schemaVersion: 1,
    generator: "frontend/scripts/generate-theme-assets.mjs",
    themeContract: {
      onLight: "Use when the logo is rendered on a light surface.",
      onDark: "Use when the logo is rendered on a dark surface.",
      runtimeThemeSwitching: "Prepared but intentionally not implemented.",
    },
    assets: manifestAssets,
  },
  null,
  2,
)}\n`;

if (checkOnly) {
  const currentManifest = await readFile(manifestPath, "utf8").catch(() => null);
  if (currentManifest !== manifest) drift.push(relative(frontendRoot, manifestPath));

  for (const kind of ["brand", "client"]) {
    const directory = resolve(outputRoot, kind);
    const entries = await readdir(directory).catch(() => []);
    for (const entry of entries.filter((name) => name.endsWith(".webp"))) {
      const candidate = resolve(directory, entry);
      if (!expectedOutputs.has(candidate)) drift.push(relative(frontendRoot, candidate));
    }
  }

  if (drift.length > 0) {
    for (const path of [...new Set(drift)].sort()) console.error(`asset drift: ${path}`);
    process.exit(1);
  }
  console.log(`Verified ${expectedOutputs.size} deterministic theme-ready image variants.`);
} else {
  await mkdir(dirname(manifestPath), { recursive: true });
  await writeFile(manifestPath, manifest);
  console.log(`Generated ${expectedOutputs.size} theme-ready image variants and manifest.`);
}
