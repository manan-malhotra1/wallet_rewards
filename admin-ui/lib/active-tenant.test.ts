/**
 * Tests for active-tenant resolution.
 *
 * The regression these pin down: a `sasai_active_tenant` cookie left over from
 * a previous deployment on the same origin (e.g. a re-seeded local DB, which
 * mints a fresh tenant id) named a tenant the operator cannot access.
 * `getActiveTenant()` self-healed to the first accessible tenant while
 * `getActiveTenantId()` returned the stale id verbatim — so the shell rendered
 * one tenant's name while every tenant-scoped query asked about another,
 * surfacing as an empty "No user found" page under a confident header.
 */
import { beforeEach, describe, expect, test, vi } from "vitest";

import type { Tenant } from "@/lib/api-types";

// `active-tenant` is a server module. The `server-only` guard is aliased to a
// stub by vitest.config.ts; here we stub the next/headers cookie store and
// `@/auth`, so importing the API client does not pull next-auth into jsdom.
vi.mock("@/auth", () => ({ auth: vi.fn() }));

const cookieStore = { get: vi.fn() };
vi.mock("next/headers", () => ({ cookies: async () => cookieStore }));

vi.mock("@/lib/api-endpoints", () => ({ listTenants: vi.fn() }));

const { listTenants } = await import("@/lib/api-endpoints");
const { getActiveTenant, getActiveTenantId } = await import("@/lib/active-tenant");
const { ApiError } = await import("@/lib/api");

/** Minimal Tenant record — only `id`/`name` matter to the resolver. */
function tenant(id: string, name: string): Tenant {
  return { id, name } as Tenant;
}

const SASAI = tenant("69519a33-aaaa-4a34-83e2-c9545fb8dddd", "Sasai-ZA");
const OTHER = tenant("11111111-bbbb-4a34-83e2-c9545fb8dddd", "Sasai-ZW");

/** Point the cookie store at `value`, or at no cookie when undefined. */
function setCookie(value: string | undefined) {
  cookieStore.get.mockReturnValue(value === undefined ? undefined : { value });
}

beforeEach(() => {
  vi.mocked(listTenants).mockReset();
  cookieStore.get.mockReset();
  vi.mocked(listTenants).mockResolvedValue([SASAI, OTHER]);
});

describe("getActiveTenantId", () => {
  test("returns the cookie's tenant when the operator can access it", async () => {
    setCookie(OTHER.id);
    expect(await getActiveTenantId()).toBe(OTHER.id);
  });

  test("falls back to the first accessible tenant when the cookie is stale", async () => {
    setCookie("46f76c69-dead-4549-b5a7-607fc51ab8fc"); // not in the tenant list
    expect(await getActiveTenantId()).toBe(SASAI.id);
  });

  test("falls back to the first accessible tenant when there is no cookie", async () => {
    setCookie(undefined);
    expect(await getActiveTenantId()).toBe(SASAI.id);
  });

  test("returns null when the operator has no tenants", async () => {
    setCookie("46f76c69-dead-4549-b5a7-607fc51ab8fc");
    vi.mocked(listTenants).mockResolvedValue([]);
    expect(await getActiveTenantId()).toBeNull();
  });

  test("returns null when the backend rejects the tenant list", async () => {
    setCookie(SASAI.id);
    vi.mocked(listTenants).mockRejectedValue(
      new ApiError(403, "forbidden", "No tenant access"),
    );
    expect(await getActiveTenantId()).toBeNull();
  });
});

describe("resolver agreement", () => {
  test("both resolvers name the same tenant for a stale cookie", async () => {
    setCookie("46f76c69-dead-4549-b5a7-607fc51ab8fc");

    const id = await getActiveTenantId();
    const record = await getActiveTenant();

    // The invariant the bug broke: the tenant the shell *displays* is always
    // the tenant tenant-scoped queries are *sent for*.
    expect(id).toBe(record?.id);
  });
});
