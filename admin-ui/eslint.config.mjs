/**
 * ESLint flat config (ESLint v9 + Next 16).
 *
 * Next 16 removed the `next lint` command, so linting runs through the ESLint
 * CLI (`npm run lint` → `eslint .`). eslint-config-next@16 ships a native flat
 * config as its default export (core-web-vitals + typescript rules), spread here.
 */
import next from "eslint-config-next";

const config = [
  ...next,
  {
    // Build output, deps, and generated test artifacts — never lint these
    // (the Playwright report ships minified vendor bundles that choke eslint).
    ignores: [
      ".next/**",
      "node_modules/**",
      "coverage/**",
      "playwright-report/**",
      "test-results/**",
      "next-env.d.ts",
    ],
  },
  {
    // Two opinionated presets that eslint-config-next 16 turns on as ERRORS but
    // which fire on standard, intentional patterns throughout our (tested)
    // component layer — kept as WARNINGS so `npm run lint` stays a useful gate
    // for real problems rather than failing on these:
    //  - set-state-in-effect: the controlled-dialog reset (setForm on `open`
    //    change) and mount-guard (`setMounted(true)`) patterns are deliberate.
    //  - no-unescaped-entities: literal apostrophes in copy read fine.
    rules: {
      "react-hooks/set-state-in-effect": "warn",
      "react/no-unescaped-entities": "warn",
    },
  },
];

export default config;
