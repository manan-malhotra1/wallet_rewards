/**
 * Tailwind v4 uses the new PostCSS plugin; that's the only thing this file
 * needs to wire up. Autoprefixer is handled by `@tailwindcss/postcss`.
 */
const config = {
  plugins: {
    "@tailwindcss/postcss": {},
  },
};

export default config;
