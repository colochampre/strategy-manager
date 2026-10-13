import { describe, expect, it } from "vitest";

import { pendingProposalNames } from "@/features/positions/pendingProposal";

const proposal = (over: Partial<{ state: string; allocation_id: string; discrepancy_id: string }> = {}) => ({
  state: "PENDING",
  allocation_id: "alloc-1",
  discrepancy_id: "disc-1",
  ...over,
});

describe("pendingProposalNames", () => {
  it("is true when a pending proposal carries both the allocation and the discrepancy", () => {
    expect(pendingProposalNames([proposal()], "alloc-1", "disc-1")).toBe(true);
  });

  it("is false when the proposal is not pending", () => {
    expect(pendingProposalNames([proposal({ state: "APPROVED" })], "alloc-1", "disc-1")).toBe(false);
  });

  it("is false when the proposal is for another allocation", () => {
    expect(pendingProposalNames([proposal({ allocation_id: "alloc-2" })], "alloc-1", "disc-1")).toBe(false);
  });

  it("is false when the proposal is for another discrepancy", () => {
    expect(pendingProposalNames([proposal({ discrepancy_id: "disc-2" })], "alloc-1", "disc-1")).toBe(false);
  });

  it("is false for an empty list", () => {
    expect(pendingProposalNames([], "alloc-1", "disc-1")).toBe(false);
  });

  it("finds the one that matches among others that do not", () => {
    const list = [proposal({ allocation_id: "alloc-2" }), proposal({ state: "REJECTED" }), proposal()];
    expect(pendingProposalNames(list, "alloc-1", "disc-1")).toBe(true);
  });
});
