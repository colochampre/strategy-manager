import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DeleteStrategyDialog } from "@/features/strategies/DeleteStrategyDialog";
import { ApiError } from "@/shared/api/client";
import i18n from "@/shared/i18n";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";

const NAME = "ETH Breakout";

const KEYS = [
  "button",
  "cancel",
  "confirm",
  "confirmBody",
  "confirmTitle",
  "description",
  "disabledHint",
  "errors.generic",
  "errors.hasHistory",
  "errors.stillEnabled",
  "history.bookingProposals_one",
  "history.bookingProposals_other",
  "history.enablementEvents_one",
  "history.enablementEvents_other",
  "history.executionAttempts_one",
  "history.executionAttempts_other",
  "history.ledgerEntries_one",
  "history.ledgerEntries_other",
  "history.reservations_one",
  "history.reservations_other",
  "history.signals_one",
  "history.signals_other",
  "pending",
  "title",
  "typeName",
];

function flatten(node: unknown, prefix = ""): string[] {
  if (typeof node === "string") return [prefix];
  if (typeof node !== "object" || node === null) return [];
  return Object.entries(node).flatMap(([key, value]) => flatten(value, prefix ? `${prefix}.${key}` : key));
}

function refusal(code: string, history?: unknown) {
  return new ApiError(409, { detail: { error: code, message: "server text", history } });
}

const HISTORY = {
  signals: 3,
  reservations: 0,
  execution_attempts: 0,
  ledger_entries: 2,
  booking_proposals: 0,
  enablement_events: 0,
};

function renderDialog(props: Partial<Parameters<typeof DeleteStrategyDialog>[0]> = {}) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  render(<DeleteStrategyDialog name={NAME} pending={false} error={null} onConfirm={onConfirm} onCancel={onCancel} {...props} />);
  return { onConfirm, onCancel };
}

function typeName(value: string) {
  fireEvent.change(screen.getByLabelText(i18n.t("strategies.delete.typeName")), { target: { value } });
}

function confirmButton() {
  return screen.getByRole("button", { name: i18n.t("strategies.delete.confirm") });
}

afterEach(async () => {
  await i18n.changeLanguage("en");
});

describe("DeleteStrategyDialog", () => {
  it("keeps confirm disabled until the typed text equals the name", () => {
    const { onConfirm } = renderDialog();
    expect(confirmButton()).toBeDisabled();

    typeName("ETH breakout");
    expect(confirmButton()).toBeDisabled();
    typeName(`${NAME} `);
    expect(confirmButton()).toBeDisabled();

    typeName(NAME);
    expect(confirmButton()).toBeEnabled();
    fireEvent.click(confirmButton());
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("does not confirm on Enter in the field while the name does not match", () => {
    const { onConfirm } = renderDialog();
    const field = screen.getByLabelText(i18n.t("strategies.delete.typeName")) as HTMLInputElement;

    typeName("ETH");
    fireEvent.submit(field.form as HTMLFormElement);
    expect(onConfirm).not.toHaveBeenCalled();

    typeName(NAME);
    fireEvent.submit(field.form as HTMLFormElement);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("calls onCancel on the cancel button, on Escape and on a cancel event, and never onConfirm", () => {
    const { onConfirm, onCancel } = renderDialog();
    typeName(NAME);
    const dialog = screen.getByRole("dialog");

    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.delete.cancel") }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(2);
    fireEvent(dialog, new Event("cancel", { cancelable: true }));
    expect(onCancel).toHaveBeenCalledTimes(3);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("states that the delete cannot be undone and names the strategy", () => {
    renderDialog();
    const dialog = screen.getByRole("dialog", { name: i18n.t("strategies.delete.confirmTitle", { name: NAME }) });
    expect(dialog).toHaveTextContent(i18n.t("strategies.delete.confirmBody", { name: NAME }));
    expect(i18n.t("strategies.delete.confirmBody", { name: NAME })).toMatch(/cannot be undone/);
  });

  it("renders the still-enabled refusal", () => {
    renderDialog({ error: refusal("STILL_ENABLED") });
    expect(screen.getByRole("alert")).toHaveTextContent(i18n.t("strategies.delete.errors.stillEnabled"));
  });

  it("names each non-zero kind with its count and no zero kind", () => {
    renderDialog({ error: refusal("HAS_HISTORY", HISTORY) });
    const items = within(screen.getByRole("alert")).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      i18n.t("strategies.delete.history.signals", { count: 3 }),
      i18n.t("strategies.delete.history.ledgerEntries", { count: 2 }),
    ]);
    expect(screen.queryByText(i18n.t("strategies.delete.history.reservations", { count: 0 }))).toBeNull();
  });

  it("renders a refusal naming enablement events like any other kind", () => {
    renderDialog({ error: refusal("HAS_HISTORY", { ...HISTORY, signals: 0, ledger_entries: 0, enablement_events: 1 }) });
    const items = within(screen.getByRole("alert")).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([i18n.t("strategies.delete.history.enablementEvents", { count: 1 })]);
  });

  it("says the strategy can be archived instead", () => {
    renderDialog({ error: refusal("HAS_HISTORY", HISTORY) });
    expect(screen.getByRole("alert")).toHaveTextContent(i18n.t("strategies.delete.errors.hasHistory"));
    expect(i18n.t("strategies.delete.errors.hasHistory")).toMatch(/Archive it instead/);
  });

  it.each([
    ["missing", undefined],
    ["not an object", "three signals"],
    ["with a non-integer count", { ...HISTORY, signals: "3" }],
    ["with a negative count", { ...HISTORY, signals: -1 }],
  ])("shows the main sentence alone when the history is %s", (_label, history) => {
    renderDialog({ error: refusal("HAS_HISTORY", history) });
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(i18n.t("strategies.delete.errors.hasHistory"));
    expect(within(alert).queryAllByRole("listitem")).toHaveLength(0);
  });

  it("renders the generic refusal for any other error", () => {
    renderDialog({ error: new Error("boom") });
    expect(screen.getByRole("alert")).toHaveTextContent(i18n.t("strategies.delete.errors.generic"));
  });

  it("disables both buttons while pending", () => {
    renderDialog({ pending: true });
    typeName(NAME);
    expect(screen.getByRole("button", { name: i18n.t("strategies.delete.pending") })).toBeDisabled();
    expect(screen.getByRole("button", { name: i18n.t("strategies.delete.cancel") })).toBeDisabled();
  });

  it("ignores Escape while a delete is in flight", () => {
    const { onCancel } = renderDialog({ pending: true });
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("gives every control an accessible name", () => {
    renderDialog();
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(2);
    for (const button of buttons) expect(button).toHaveAccessibleName(/\S/);
    expect(screen.getByRole("textbox")).toHaveAccessibleName(i18n.t("strategies.delete.typeName"));
  });

  it("renders its texts in Spanish", async () => {
    await i18n.changeLanguage("es");
    renderDialog({ error: refusal("HAS_HISTORY", HISTORY) });
    expect(screen.getByRole("dialog", { name: es.strategies.delete.confirmTitle.replace("{{name}}", NAME) })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(es.strategies.delete.errors.hasHistory);
  });

  it("has every key in en and es", () => {
    expect(flatten(en.strategies.delete).sort()).toEqual(KEYS);
    expect(flatten(es.strategies.delete).sort()).toEqual(KEYS);
  });
});
