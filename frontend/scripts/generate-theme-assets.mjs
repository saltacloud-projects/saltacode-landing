import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { dirname, relative, resolve } from "node:path";

import sharp from "sharp";

const frontendRoot = resolve(import.meta.dirname, "..");
const outputRoot = resolve(frontendRoot, "src/assets/optimized");
const manifestPath = resolve(outputRoot, "manifest.json");
const checkOnly = process.argv.includes("--check");

const appIcons = [
  {
    id: "favicon",
    source: "src/assets/brand/logo_nav_light.png",
    output: "public/favicon.png",
    canvas: { width: 256, height: 256, maxWidth: 224, maxHeight: 224 },
    background: "#ffffff",
  },
  {
    id: "apple-touch-icon",
    source: "src/assets/brand/logo_nav_light.png",
    output: "public/apple-touch-icon.png",
    canvas: { width: 180, height: 180, maxWidth: 144, maxHeight: 144 },
    background: "#ffffff",
  },
];

const serviceSourceContract = Object.freeze({
  configuredOutputMaximumWidth: 960,
  cssSlotMaximumWidth: 540,
  maximumDimension: 1440,
  format: "webp",
  quality: 92,
  smartSubsample: true,
  effort: 6,
});
const serviceSourceMasters = ["consulting", "outsourcing", "saas", "software-factory"].map(
  (id) => ({ id, path: `src/assets/services/${id}.webp` }),
);

const clientCanvas = Object.freeze({ width: 360, height: 160, maxWidth: 320, maxHeight: 120 });
const clientPalette = Object.freeze({ onLight: "#74747D", onDark: "#D8D8E0" });

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
    ["coseguro-total", "src/assets/clients/logo-coseguro-total.png"],
    ["mariana-prone", "src/assets/clients/logo-sitio-mariana-prone.png"],
  ].map(([slug, source]) => ({
    id: `client-${slug}`,
    kind: "client",
    canvas: clientCanvas,
    variants: {
      onLight: { source, color: clientPalette.onLight },
      onDark: { source, color: clientPalette.onDark },
    },
  })),
  {
    id: "client-finanx",
    kind: "client",
    canvas: clientCanvas,
    variants: {
      onLight: {
        source: "src/assets/clients/finanx.png",
        color: clientPalette.onLight,
        removeBackground: { color: "#013660", tolerance: 18, feather: 32 },
      },
      onDark: {
        source: "src/assets/clients/finanx.png",
        color: clientPalette.onDark,
        removeBackground: { color: "#013660", tolerance: 18, feather: 32 },
      },
    },
  },
  {
    id: "client-metalnor",
    kind: "client",
    canvas: clientCanvas,
    variants: {
      onLight: {
        source: "src/assets/clients/metalnor-on-light.png",
        color: clientPalette.onLight,
        inkMask: { lightStart: 0.52, lightEnd: 0.72 },
      },
      onDark: {
        source: "src/assets/clients/metalnor-on-light.png",
        color: clientPalette.onDark,
        inkMask: { lightStart: 0.52, lightEnd: 0.72 },
      },
    },
  },
  {
    id: "client-cocel",
    kind: "client",
    canvas: clientCanvas,
    variants: {
      onLight: {
        source: "src/assets/clients/cocel-on-light.png",
        color: clientPalette.onLight,
      },
      onDark: {
        source: "src/assets/clients/cocel-on-dark.png",
        color: clientPalette.onDark,
      },
    },
  },
];

function sha256(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

function outputPath(asset, theme) {
  return resolve(outputRoot, asset.kind, `${asset.id.replace(`${asset.kind}-`, "")}-${theme}.webp`);
}

function parseHexColor(color) {
  const match = /^#([\da-f]{2})([\da-f]{2})([\da-f]{2})$/i.exec(color);
  if (!match) throw new Error(`Unsupported background color: ${color}`);
  return match.slice(1).map((channel) => Number.parseInt(channel, 16));
}

async function removeBackground(sourceBuffer, settings) {
  const { data, info } = await sharp(sourceBuffer)
    .ensureAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true });
  const [backgroundRed, backgroundGreen, backgroundBlue] = parseHexColor(settings.color);

  for (let offset = 0; offset < data.length; offset += 4) {
    const redDelta = data[offset] - backgroundRed;
    const greenDelta = data[offset + 1] - backgroundGreen;
    const blueDelta = data[offset + 2] - backgroundBlue;
    const distance = Math.sqrt(redDelta ** 2 + greenDelta ** 2 + blueDelta ** 2);
    const coverage = Math.min(
      1,
      Math.max(0, (distance - settings.tolerance) / settings.feather),
    );
    data[offset + 3] = Math.round(data[offset + 3] * coverage);
  }

  return sharp(data, { raw: info }).png().toBuffer();
}

async function createInkMask(sourceBuffer, settings) {
  const { data, info } = await sharp(sourceBuffer)
    .ensureAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true });
  const range = settings.lightEnd - settings.lightStart;

  for (let offset = 0; offset < data.length; offset += 4) {
    const luminance =
      (0.2126 * data[offset] + 0.7152 * data[offset + 1] + 0.0722 * data[offset + 2]) /
      255;
    const inkCoverage = Math.min(1, Math.max(0, (settings.lightEnd - luminance) / range));
    data[offset] = 255;
    data[offset + 1] = 255;
    data[offset + 2] = 255;
    data[offset + 3] = Math.round(data[offset + 3] * inkCoverage);
  }

  return sharp(data, { raw: info }).png().toBuffer();
}

async function trimAndResize(sourceBuffer, canvas) {
  const trimmed = await sharp(sourceBuffer)
    .ensureAlpha()
    .trim({ background: { r: 0, g: 0, b: 0, alpha: 0 }, threshold: 8 })
    .png()
    .toBuffer({ resolveWithObject: true });
  const resized = await sharp(trimmed.data)
    .resize({
      width: canvas.maxWidth,
      height: canvas.maxHeight,
      fit: "inside",
      kernel: sharp.kernel.lanczos3,
      withoutEnlargement: false,
    })
    .png()
    .toBuffer({ resolveWithObject: true });

  return { resized, trimmed };
}

function placeOnCanvas(foreground, foregroundInfo, canvas, background) {
  const left = Math.round((canvas.width - foregroundInfo.width) / 2);
  const top = Math.round((canvas.height - foregroundInfo.height) / 2);

  return sharp({
    create: {
      width: canvas.width,
      height: canvas.height,
      channels: 4,
      background,
    },
  }).composite([{ input: foreground, left, top }]);
}

async function normalizeServiceSource(master) {
  const sourcePath = resolve(frontendRoot, master.path);
  let sourceBuffer = await readFile(sourcePath);
  let metadata = await sharp(sourceBuffer).metadata();
  const sourceMaximumDimension = Math.max(metadata.width ?? 0, metadata.height ?? 0);

  if (!checkOnly && sourceMaximumDimension > serviceSourceContract.maximumDimension) {
    sourceBuffer = await sharp(sourceBuffer)
      .resize({
        width: serviceSourceContract.maximumDimension,
        height: serviceSourceContract.maximumDimension,
        fit: "inside",
        kernel: sharp.kernel.lanczos3,
        withoutEnlargement: true,
      })
      .webp({
        quality: serviceSourceContract.quality,
        smartSubsample: serviceSourceContract.smartSubsample,
        effort: serviceSourceContract.effort,
      })
      .toBuffer();
    await writeFile(sourcePath, sourceBuffer);
    metadata = await sharp(sourceBuffer).metadata();
  }

  const maximumDimension = Math.max(metadata.width ?? 0, metadata.height ?? 0);
  const hasContractDrift =
    metadata.format !== serviceSourceContract.format ||
    maximumDimension !== serviceSourceContract.maximumDimension;
  if (hasContractDrift) {
    if (checkOnly) drift.push(master.path);
    else throw new Error(`Service source does not satisfy the source contract: ${master.path}`);
  }

  return {
    id: master.id,
    path: master.path,
    bytes: sourceBuffer.byteLength,
    sha256: sha256(sourceBuffer),
    width: metadata.width,
    height: metadata.height,
  };
}

async function renderVariant(asset, variant) {
  const sourcePath = resolve(frontendRoot, variant.source);
  const sourceBuffer = await readFile(sourcePath);
  const preparedSource = variant.removeBackground
    ? await removeBackground(sourceBuffer, variant.removeBackground)
    : sourceBuffer;
  const maskedSource = variant.inkMask
    ? await createInkMask(preparedSource, variant.inkMask)
    : preparedSource;
  const { resized, trimmed } = await trimAndResize(maskedSource, asset.canvas);

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

  const output = await placeOnCanvas(
    foreground,
    resized.info,
    asset.canvas,
    { r: 0, g: 0, b: 0, alpha: 0 },
  )
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

async function renderAppIcon(icon) {
  const sourceBuffer = await readFile(resolve(frontendRoot, icon.source));
  const { resized } = await trimAndResize(sourceBuffer, icon.canvas);
  const output = await placeOnCanvas(resized.data, resized.info, icon.canvas, icon.background)
    .png({ compressionLevel: 9, adaptiveFiltering: true })
    .toBuffer();

  return {
    source: {
      path: icon.source,
      bytes: sourceBuffer.byteLength,
      sha256: sha256(sourceBuffer),
    },
    output,
  };
}

const expectedOutputs = new Set();
const manifestAssets = [];
const manifestAppIcons = [];
const drift = [];
const manifestServiceSources = [];

for (const master of serviceSourceMasters) {
  manifestServiceSources.push(await normalizeServiceSource(master));
}

for (const asset of assets) {
  const manifestVariants = {};
  for (const [theme, variant] of Object.entries(asset.variants)) {
    if (asset.kind === "client" && variant.color !== clientPalette[theme]) {
      throw new Error(`${asset.id} ${theme} must use the shared client palette.`);
    }
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

for (const icon of appIcons) {
  const rendered = await renderAppIcon(icon);
  const target = resolve(frontendRoot, icon.output);
  manifestAppIcons.push({
    id: icon.id,
    source: rendered.source,
    output: {
      path: icon.output,
      bytes: rendered.output.byteLength,
      sha256: sha256(rendered.output),
      width: icon.canvas.width,
      height: icon.canvas.height,
    },
  });

  if (checkOnly) {
    const current = await readFile(target).catch(() => null);
    if (!current || !current.equals(rendered.output)) drift.push(icon.output);
  } else {
    await mkdir(dirname(target), { recursive: true });
    await writeFile(target, rendered.output);
  }
}

const manifest = `${JSON.stringify(
  {
    schemaVersion: 1,
    generator: "frontend/scripts/generate-theme-assets.mjs",
    themeContract: {
      onLight: "Use when the logo is rendered on a light surface.",
      onDark: "Use when the logo is rendered on a dark surface.",
      runtimeThemeSwitching: "Implemented by the pre-paint bootstrap and theme-controller.ts.",
    },
    assets: manifestAssets,
    appIcons: manifestAppIcons,
    serviceSourceContract,
    serviceSourceMasters: manifestServiceSources,
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
  console.log(
    `Verified ${expectedOutputs.size} deterministic theme-ready image variants and ${manifestServiceSources.length} service source masters.`,
  );
} else {
  await mkdir(dirname(manifestPath), { recursive: true });
  await writeFile(manifestPath, manifest);
  console.log(
    `Generated ${expectedOutputs.size} theme-ready image variants, normalized ${manifestServiceSources.length} service source masters, and wrote the manifest.`,
  );
}
