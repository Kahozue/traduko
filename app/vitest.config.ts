import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // labels.test.ts imports the core's seeds.py (?raw) to cross-check stage
  // label coverage; allow reads from the repo root, not just app/.
  server: { fs: { allow: [".."] } },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    exclude: ["tests/**", "node_modules/**", "src-tauri/**"],
    globals: true,
  },
});
