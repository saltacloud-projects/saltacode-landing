import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Development must never silently proxy to another project's production API.
const apiTarget = process.env.PANEL_API_TARGET;

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: apiTarget
      ? { "/api": { target: apiTarget, changeOrigin: true } }
      : undefined,
  },
});
