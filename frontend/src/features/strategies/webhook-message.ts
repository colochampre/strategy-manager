import template from "@/features/strategies/webhook-message.fixture.json";

/**
 * The alert message the owner pastes into TradingView for one strategy: the
 * exact JSON `TradingViewAlert.from_payload` documents, with `signal_type`
 * set to the strategy's id. TradingView fills the `{{...}}` placeholders when
 * the alert fires.
 *
 * It is rendered from `webhook-message.fixture.json`, the file a backend test
 * parses through the real alert parser, so the message cannot drift from what
 * the webhook accepts. `signal_type` keeps the fixture's own position in the
 * object; only its value is replaced.
 */
export function webhookMessage(strategyId: string): string {
  return JSON.stringify({ ...template, signal_type: strategyId }, null, 2);
}
