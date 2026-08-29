/**
 * Vitest configuration for the admin UI.
 *
 * Frontend automation testing was previously deferred (coding-guidelines.md §4)
 * and is now ACTIVE: this stands up a jsdom DOM environment so lib helpers and
 * key interactive components can be unit/component-tested with Testing Library.
 *
 * The `@/` alias is derived from tsconfig.json's `paths` at load time so it can
 * never drift from what Next.js and the type checker resolve at build time.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { defineConfig } from "vitest/config";

const projectRoot = dirname(fileURLToPath(import.meta.url));

/**
 * Read the `@/*` target from tsconfig `paths` (e.g. "./*") and turn it into an
 * absolute directory, so the test alias tracks the source of truth. Falls back
 * to the project root if the entry is ever renamed.
 */
function aliasRootFromTsconfig(): string {
  const tsconfig = JSON.parse(readFileSync(resolve(projectRoot, "tsconfig.json"), "utf8"));
  const target: string | undefined = tsconfig.compilerOptions?.paths?.["@/*"]?.[0];
  const baseUrl: string = tsconfig.compilerOptions?.baseUrl ?? ".";
  // "./*" -> "." ; strip the trailing glob segment to get the directory.
  const dir = (target ?? "./*").replace(/\/?\*$/, "") || ".";
  return resolve(projectRoot, baseUrl, dir);
}

export default defineConfig({
  resolve: {
    alias: {
      // Mirror tsconfig `paths`: "@/*" -> "./*" (the admin-ui project root).
      "@": aliasRootFromTsconfig(),
      // `server-only` is not an installed package — Next aliases it at build
      // time. Without this, any test importing a server module fails to
      // resolve the specifier. See vitest.stubs/server-only.ts.
      "server-only": resolve(projectRoot, "vitest.stubs/server-only.ts"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["**/*.test.{ts,tsx}"],
    // node_modules and build output are never test sources.
    exclude: ["node_modules/**", ".next/**"],
    // jsdom + userEvent + Radix dialogs are slow under full-suite parallel load;
    // the 5s default flakes on interaction tests that pass comfortably alone.
    testTimeout: 20000,
    hookTimeout: 20000,
  },
});
