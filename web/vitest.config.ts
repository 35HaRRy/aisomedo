import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    include: ["src/**/*.test.{ts,tsx}"], environment: "jsdom", setupFiles: ["./src/test/setup.ts"],
    // Let jsdom supply browser storage instead of Node 26's native globals.
    poolOptions: { forks: { execArgv: ["--no-experimental-webstorage"] } },
  },
});
