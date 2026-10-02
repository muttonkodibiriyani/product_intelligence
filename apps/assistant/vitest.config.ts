import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["test/**/*.test.ts"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.ts"],
      reporter: ["text", "text-summary"],
      thresholds: { lines: 90, functions: 90, branches: 85, statements: 90 },
    },
  },
});
