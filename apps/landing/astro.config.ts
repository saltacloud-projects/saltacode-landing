import { defineConfig } from "astro/config";

export default defineConfig({
  site: "https://saltacode.com.ar",
  output: "static",
  trailingSlash: "always",
  build: {
    format: "directory",
  },
});
