import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["apps/*/tests/**/*.test.ts", "packages/*/tests/**/*.test.ts"],
    exclude: ["**/node_modules/**", "apps/field-console/e2e/**"],
    environment: "node",
  },
});
