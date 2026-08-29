/**
 * Test stub for the `server-only` guard.
 *
 * `server-only` is not a real installed dependency — Next.js aliases the
 * specifier at build time to a module that throws when a client bundle imports
 * it. Under vitest there is no such alias, so importing any server module
 * (`lib/api.ts`, `lib/api-endpoints.ts`, `lib/active-tenant.ts`) fails to
 * resolve. vitest.config.ts aliases the specifier here instead: the guard is a
 * build-time assertion with no runtime behaviour, so an empty module is the
 * faithful stand-in.
 */
export {};
