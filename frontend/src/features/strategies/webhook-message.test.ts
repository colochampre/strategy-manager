import { describe, expect, it } from "vitest";

import { webhookMessage } from "@/features/strategies/webhook-message";
import fixtureText from "@/features/strategies/webhook-message.fixture.json?raw";

const ID = "11111111-1111-4111-8111-111111111111";
const OTHER_ID = "22222222-2222-4222-8222-222222222222";

/**
 * The exact JSON `TradingViewAlert.from_payload` documents (signals/domain/alert.py),
 * written out here a second time on purpose: the fixture is read from disk below, and
 * this literal is what the shape must be, so editing the fixture alone cannot pass.
 */
function documentedShape(strategyId: string) {
  return {
    data: {
      action: "{{strategy.order.action}}",
      contracts: "{{strategy.order.contracts}}",
      position_size: "{{strategy.position_size}}",
    },
    price: "{{close}}",
    signal_param: "{}",
    signal_type: strategyId,
    symbol: "{{ticker}}",
    time: "{{timenow}}",
  };
}

describe("webhookMessage", () => {
  it("renders the documented alert JSON with the strategy id as signal_type", () => {
    expect(JSON.parse(webhookMessage(ID))).toEqual(documentedShape(ID));
  });

  it("changes only signal_type when the strategy changes", () => {
    const first = JSON.parse(webhookMessage(ID)) as Record<string, unknown>;
    const second = JSON.parse(webhookMessage(OTHER_ID)) as Record<string, unknown>;

    expect({ ...first, signal_type: OTHER_ID }).toEqual(second);
    expect(second.signal_type).toBe(OTHER_ID);
  });

  it("is the fixture file on disk with signal_type substituted, key for key", () => {
    const fixture = JSON.parse(fixtureText) as Record<string, unknown>;

    expect(JSON.parse(webhookMessage(ID))).toEqual({ ...fixture, signal_type: ID });
    expect(Object.keys(JSON.parse(webhookMessage(ID)) as object)).toEqual(Object.keys(fixture));
  });

  it("leaves every TradingView placeholder for TradingView to fill", () => {
    const placeholders = webhookMessage(ID).match(/\{\{[^{}]+\}\}/g);

    expect(placeholders).toEqual([
      "{{strategy.order.action}}",
      "{{strategy.order.contracts}}",
      "{{strategy.position_size}}",
      "{{close}}",
      "{{ticker}}",
      "{{timenow}}",
    ]);
  });
});
