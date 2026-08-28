import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { siFacebook, siGooglemaps, siInstagram, siWhatsapp } from "simple-icons";

const outputPath = resolve(import.meta.dirname, "../public/icons/site-icons.svg");
const checkOnly = process.argv.includes("--check");
const icons = {
  email: "M2 4h20v16H2V4zm10 8.2L4.7 6h14.6L12 12.2zM4 18h16V8.1l-8 6.8-8-6.8V18z",
  facebook: siFacebook.path,
  "google-maps": siGooglemaps.path,
  instagram: siInstagram.path,
  linkedin: "M20.45 20.45h-3.56v-5.57c0-1.33-.03-3.03-1.85-3.03-1.86 0-2.14 1.44-2.14 2.94v5.66H9.35V9h3.42v1.56h.04c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 7.43a2.06 2.06 0 1 1 0-4.13 2.06 2.06 0 0 1 0 4.13zM7.12 20.45H3.56V9h3.56v11.45zM22.23 0H1.77C.79 0 0 .77 0 1.73v20.54C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.73V1.73C24 .77 23.2 0 22.22 0h.01z",
  phone: "M6.62 10.79a15.46 15.46 0 0 0 6.59 6.59l2.2-2.2a1 1 0 0 1 1.02-.24c1.12.37 2.33.57 3.57.57a1 1 0 0 1 1 1V20a1 1 0 0 1-1 1C10.61 21 3 13.39 3 4a1 1 0 0 1 1-1h3.5a1 1 0 0 1 1 1c0 1.25.2 2.45.57 3.57a1 1 0 0 1-.25 1.02l-2.2 2.2z",
  whatsapp: siWhatsapp.path,
};
const output = `<svg xmlns="http://www.w3.org/2000/svg">\n${Object.entries(icons)
  .map(([name, path]) => `  <symbol id="site-icon-${name}" viewBox="0 0 24 24"><path d="${path}"/></symbol>`)
  .join("\n")}\n</svg>\n`;

if (checkOnly) {
  const current = await readFile(outputPath, "utf8").catch(() => "");
  if (current !== output) throw new Error("The generated site icon sprite is stale. Run pnpm --dir frontend icons:generate.");
  console.log("Verified the deterministic site icon sprite.");
} else {
  await mkdir(dirname(outputPath), { recursive: true });
  await writeFile(outputPath, output);
  console.log(`Generated ${outputPath}.`);
}
