/**
 * Global test setup, loaded by vitest before every test file.
 *
 * - Registers `@testing-library/jest-dom` matchers (toBeInTheDocument, etc.).
 * - Unmounts the React tree after each test so component tests stay isolated.
 * - Polyfills the handful of DOM APIs jsdom omits that Radix UI primitives
 *   (Dialog, Select) call — without these, opening a Radix menu throws.
 */
import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});

// Radix relies on these; jsdom does not implement them. No-op shims are enough
// for the interactions our component tests drive.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
}
if (!Element.prototype.setPointerCapture) {
  Element.prototype.setPointerCapture = () => {};
}
if (!Element.prototype.releasePointerCapture) {
  Element.prototype.releasePointerCapture = () => {};
}
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList;
}
