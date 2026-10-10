import { useQuery } from "@tanstack/react-query";

import type { SharePreview } from "@/shared/api/types";

/**
 * STUBS (12f.10.7 RED): a well-formed body whose amounts are all zero, no request, no check and a key that
 * no other query shares, until the GREEN reads `GET /strategies/{id}/share-preview`.
 */
export function fetchSharePreview(strategyId: string, _share?: string): Promise<SharePreview> {
  return Promise.resolve({
    strategy_id: strategyId,
    pool: { exchange: "", venue: "", settlement_currency: "" },
    currency: "",
    pool_minimum: "0",
    balance: null,
    exact: null,
    steps: [],
  });
}

export function useSharePreview(strategyId: string, share?: string) {
  return useQuery({
    queryKey: ["share-preview-stub"],
    queryFn: () => fetchSharePreview(strategyId, share),
  });
}
