/**
 * TanStack Query client + query-key factory.
 *
 * The wallet is the only authenticated read in this dispatch; P2P + topup
 * arrive in dispatch 2 and will register more keys here. Defaults are
 * conservative — refetch on focus is OFF so the demo doesn't surprise us
 * with spurious 401s on simulator re-open.
 */
import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  },
});

/** Centralised query keys — change here to invalidate everywhere. */
export const qk = {
  wallet: () => ['wallet'] as const,
  /** Services the current user may initiate on mobile (drives the pay tiles). */
  services: () => ['me-services'] as const,
};
