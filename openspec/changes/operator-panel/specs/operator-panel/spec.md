# Operator Panel Specification

## Purpose

Behavioural contract for the single-user operator panel: layout shell,
exchange scoping, the Overview, Strategies, and Settings views, and their
empty/loading/secret-handling behaviour. This spec describes WHAT the panel
must do; visual design (layout composition, typography, chart styling) is
explicitly out of scope and belongs to the design phase with the
frontend-design plugin.

> **Revised 2026-09-24.** Aligned with owner decision 18 (one key per
> exchange; a read-only key is accepted and marked), decision 19 (visual
> direction A; its approved mockups `visual/project/{Main,Strategy,Settings,
> Mobile}.dc.html` fix where the exchange bar appears and where the pending
> bookings sit on a phone), and the proposal's "secrets never rendered" rule for
> the webhook secret. The visual design itself lives in `design.md`.
>
> **Revised 2026-09-25 (owner decisions 20, 22, 23, new and binding).** A
> DEGRADED (keyless) exchange is marked "no key" alongside the read-only mark
> (decision 20). Settings gains a delete-key control (decision 22). The
> "secrets never rendered" rule for the webhook secret is withdrawn: it is
> now revealed only on an explicit request (decision 23), replacing the
> requirement below of the same area.

## Requirements

### Requirement: Shared Layout Shell

The panel MUST present a shared layout shell consisting of a top bar, a
sidebar navigation for Overview, Strategies, and Settings on wide viewports,
and the same navigation as a bottom bar on small viewports. The top bar MUST
carry exchange selection on the exchange-scoped views (Overview, Strategies).
Settings is not exchange-scoped: it lists every exchange and its top bar
carries no exchange selection (Settings.dc.html). An exchange whose active key
cannot trade MUST be marked read-only in the exchange selection. An exchange
with an enabled pool and no active key at all MUST be marked distinctly as
"no key" in the exchange selection (revised 2026-09-25, decision 20).

#### Scenario: A keyless (DEGRADED) exchange is marked in the exchange bar

> **Added 2026-09-25 (owner decision 20).**

- GIVEN Binance has an enabled pool and no active credential, and Bybit has a trade-capable one
- WHEN the exchange bar renders
- THEN Binance is marked "no key", and Bybit is not

#### Scenario: Sidebar navigation on a wide viewport

- GIVEN the panel is open on a wide viewport
- WHEN the shell renders
- THEN Overview, Strategies, and Settings are reachable from a sidebar

#### Scenario: Bottom bar navigation on a small viewport

- GIVEN the panel is open on a small viewport
- WHEN the shell renders
- THEN Overview, Strategies, and Settings are reachable from a bottom bar instead of a sidebar

#### Scenario: Exchange bar is present on exchange-scoped views

- GIVEN the Overview or Strategies view
- WHEN the shell renders
- THEN a top bar with exchange selection is present

#### Scenario: Settings lists every exchange without an exchange bar

- GIVEN the Settings view
- WHEN the shell renders
- THEN the top bar carries no exchange selection and Settings shows one entry per exchange

#### Scenario: A read-only exchange is marked in the exchange bar

- GIVEN Binance's active key cannot trade
- WHEN the exchange bar renders
- THEN Binance is marked read-only, and Bybit, whose key can trade, is not

### Requirement: Views Are Scoped to the Selected Exchange

Every value the panel displays that originates from a capital pool MUST be
scoped to the exchange currently selected in the top bar. Selecting a
different exchange MUST update every pool-scoped value shown, and the panel
MUST NEVER display a total that blends pools across exchanges or across
settlement currencies (rule 7).

#### Scenario: Switching exchange updates pool-scoped values

- GIVEN the panel is showing Bybit's pools
- WHEN the owner selects Binance in the exchange bar
- THEN every pool-scoped value updates to Binance's pools, and no Bybit figure remains shown as current

#### Scenario: No blended total is ever shown

- GIVEN the selected exchange has more than one settlement-currency pool
- WHEN the Overview renders
- THEN each pool's figures are shown separately and no combined total across pools appears anywhere in the shell

### Requirement: Overview Shows Balance, PnL Ranges, Curve, and Monthly Grid

The Overview view MUST show, per pool of the selected exchange: current
available balance, PnL for 7D/30D/90D/1Y/All, the compounded return curve
with drawdown from previous peak, and the monthly grid.

#### Scenario: Overview renders all required elements for a pool with data

- GIVEN pool `(bybit, usdt-m, USDT)` has closed trades
- WHEN Overview renders for Bybit
- THEN available balance, all five PnL ranges, the compounded curve with drawdown, and the monthly grid are shown for that pool

#### Scenario: Overview renders empty states under DRY_RUN

- GIVEN `DRY_RUN=true` and the ledger is empty
- WHEN Overview renders
- THEN it shows a defined empty state for the curve, monthly grid, and PnL ranges, with no error

### Requirement: Pending-Bookings Panel On Overview

The Overview view MUST show a pending-bookings panel on the right side on
wide viewports. On small viewports it MUST become an in-flow block of the
Overview column, placed after the return chart and before the monthly grid,
as in the approved Mobile.dc.html (revised 2026-09-24: decision 3 assumed
"below the dashboard"; the approved mockup of decision 19 places it here). The
panel MUST reflect only bookings relevant to the selected exchange.

#### Scenario: Pending bookings appear beside Overview on a wide viewport

- GIVEN pending booking proposals exist for the selected exchange
- WHEN Overview renders on a wide viewport
- THEN the pending-bookings panel appears to the right of the dashboard content

#### Scenario: Pending bookings appear between the chart and the grid on a small viewport

- GIVEN pending booking proposals exist for the selected exchange
- WHEN Overview renders on a small viewport
- THEN the pending-bookings panel appears as a block after the return chart and before the monthly grid

#### Scenario: No pending bookings shows an empty state

- GIVEN no pending booking proposals exist for the selected exchange
- WHEN Overview renders
- THEN the pending-bookings panel shows a defined empty state, not an error or a blank area

### Requirement: Strategies List Excludes Archived By Default

The Strategies list view MUST exclude archived strategies by default and
MUST show each listed strategy's enabled state.

#### Scenario: Archived strategy is absent from the default list

- GIVEN strategy S1 is archived
- WHEN the Strategies list renders with default filters
- THEN S1 does not appear

### Requirement: Strategy Detail Shows Stats, Uptime, and Lifecycle Controls

The strategy detail view MUST show the strategy's performance stats (PnL,
trade count, stats by pair), its cumulative uptime as "active X days" with
the first activation date, its allowed-pairs list with an edit control, and
enable/disable and archive controls.

#### Scenario: Detail shows uptime for an activated strategy

- GIVEN strategy S1 was first enabled 10 days ago and has been enabled the whole time
- WHEN S1's detail view renders
- THEN it shows "active 10 days" together with the first activation date

#### Scenario: Detail shows no activation date for a never-enabled strategy

- GIVEN strategy S2 has never been enabled
- WHEN S2's detail view renders
- THEN no first-activation date is shown

#### Scenario: Archive control is disabled or explains refusal when preconditions are unmet

- GIVEN strategy S1 is enabled
- WHEN the owner attempts to archive S1 from its detail view
- THEN the panel prevents or refuses the action and states that S1 must be disabled and flat first

### Requirement: Archive Requires Explicit Confirmation

Archiving a strategy from the panel MUST require an explicit confirmation
step before the archive request is sent.

#### Scenario: Archive is not triggered by a single click without confirmation

- GIVEN strategy S1 is disabled and flat
- WHEN the owner clicks archive once
- THEN the panel requires an explicit confirmation before the archive request is sent

#### Scenario: Confirmed archive sends the request

- GIVEN strategy S1 is disabled and flat, and the owner has confirmed the archive
- WHEN the confirmation is accepted
- THEN the archive request is sent

### Requirement: Allowed-Pairs Editing From Strategy Detail

The strategy detail view MUST allow the owner to add and remove allowed
pairs, and MUST prevent submitting an edit that would leave the strategy with
zero allowed pairs.

#### Scenario: Removing the last pair is prevented

- GIVEN strategy S1 has exactly one allowed pair
- WHEN the owner attempts to remove it without adding a replacement
- THEN the panel prevents submitting that edit

#### Scenario: Adding a pair succeeds

- GIVEN strategy S1 has allowed pairs `{ETHUSDT}`
- WHEN the owner adds `SOLUSDT` and submits
- THEN the request is sent with allowed pairs `{ETHUSDT, SOLUSDT}`

### Requirement: Copy-Ready Webhook Message, Secret Revealed Only On Explicit Request

> **Revised 2026-09-24.** The former "revealed on explicit action" wording
> contradicted the proposal ("secrets never rendered") and the design (no API
> returns `WEBHOOK_SECRET`). The panel never renders the webhook secret.
>
> **Revised 2026-09-25 (owner decision 23), superseding the 2026-09-24 text
> above.** The owner reversed this: the secret MUST be revealed, but only on
> an explicit "Show secret" request, through its own dedicated endpoint
> (`admin-api`'s `GET /api/webhook-secret`), never as part of any other
> payload.

The strategy detail view MUST show a copy-ready webhook alert message built
from the strategy's own id, following the documented alert shape. The webhook
URL MUST show a placeholder where the shared secret goes by default. The panel
MUST NOT request the secret from the server except in direct response to an
explicit "Show secret" action, MUST NOT include it in any other request or
view, and MUST restore the placeholder and discard the revealed value when the
owner leaves the view.

#### Scenario: Webhook message is copy-ready with a placeholder by default

- GIVEN strategy S1's detail view is open
- WHEN it renders
- THEN a copy-ready webhook message is shown, and the webhook URL carries a placeholder instead of the shared secret

#### Scenario: No action other than the explicit request reveals the secret

- GIVEN strategy S1's detail view is open
- WHEN the owner uses any control in the view other than "Show secret"
- THEN the shared secret is never displayed and never requested from the server

#### Scenario: The explicit request reveals the secret in place

- GIVEN strategy S1's detail view is open and the webhook URL shows the placeholder
- WHEN the owner clicks "Show secret"
- THEN the panel requests the secret from `GET /api/webhook-secret` and substitutes it into the URL in place of the placeholder

#### Scenario: Leaving the view hides the secret again

- GIVEN the secret is currently revealed in strategy S1's detail view
- WHEN the owner navigates away from that view
- THEN the placeholder is restored and the revealed value is no longer retained in the panel's state

### Requirement: Settings Manages One Key Per Exchange

> **Revised 2026-09-24 (owner decision 18).** READ and TRADE slots are
> withdrawn; each exchange has one key.
>
> **Revised 2026-09-25 (owner decision 20).** A DEGRADED exchange (an enabled
> pool with no key) is distinguished from an exchange that was never
> configured, both shown as "no key" but only the DEGRADED case marked.

The Settings view MUST show one entry per exchange, showing last-4, whether
the key reads and trades or reads only, and the stored permission snapshot
when a key is active, and MUST allow adding or replacing that exchange's key.
An exchange whose key cannot trade MUST be marked read-only and MUST state
that, with dry run off, its opening signals are refused until a key that can
trade futures is stored. An exchange with an enabled pool and no key at all
MUST be marked "no key" and MUST state that, with dry run off, its opening
signals are refused until a key is stored.

#### Scenario: An exchange with no key shows a defined empty state

- GIVEN no active credential exists for Binance and its pool is not enabled
- WHEN Settings renders
- THEN Binance's entry shows a defined empty state and an add control, not last-4 or permissions

#### Scenario: An active key shows last-4 and permissions only

- GIVEN an active credential exists for Bybit
- WHEN Settings renders
- THEN Bybit's entry shows only its last-4, its trade capability and its stored permission snapshot, never a full key or secret

#### Scenario: A read-only key is marked and explained

- GIVEN Binance's active credential cannot trade
- WHEN Settings renders
- THEN Binance's entry is marked read-only and states that live opening signals for Binance are refused until a key that can trade is stored

#### Scenario: A DEGRADED exchange is marked and explained

> **Added 2026-09-25 (owner decision 20).**

- GIVEN Binance's pool is enabled and Binance has no active credential
- WHEN Settings renders
- THEN Binance's entry is marked "no key" and states that, with dry run off, its opening signals are refused until a key is stored

### Requirement: Settings Shows the Validation Outcome On Add/Replace

Submitting a key add or replace MUST show the validation outcome to the
owner: success with the resulting last-4, trade capability and permissions
(with the read-only warning when the key cannot trade), or the specific
refusal reason (live read failed, venue unreachable, withdraw permission
present, or a concurrent save).

#### Scenario: A refused save shows its reason

- GIVEN the owner submits a key with withdraw permission
- WHEN the save is refused
- THEN the panel shows the withdraw-permission refusal reason and stores nothing

#### Scenario: A successful save shows the resulting last-4 and permissions

- GIVEN the owner submits a valid key that can trade futures
- WHEN the save succeeds
- THEN the panel shows the resulting last-4 and permission snapshot for that exchange, with no read-only warning

#### Scenario: A read-only key is saved with a warning

- GIVEN the owner submits a valid key that cannot trade
- WHEN the save succeeds
- THEN the panel shows the resulting last-4 together with the read-only warning, and the exchange is marked read-only

### Requirement: Settings Allows Deleting a Key, With Explicit Confirmation and a Stated Refusal

> **Added 2026-09-25 (owner decision 22).**

An exchange with an active key MUST offer a delete control in Settings. Using
it MUST require an explicit confirmation step before the delete request is
sent. A refused delete MUST show the specific reason (an enabled strategy on
that exchange, or an open position/live reservation on that exchange), naming
what is unmet. A successful delete MUST update that exchange's entry to the
same defined empty state shown for an exchange that was never configured.

#### Scenario: Deleting is not triggered by a single click without confirmation

- GIVEN Bybit has an active key
- WHEN the owner clicks "Delete key" once
- THEN the panel requires an explicit confirmation before the delete request is sent

#### Scenario: A refused delete states why

- GIVEN Bybit has an active key and an enabled strategy bound to its pool
- WHEN the owner confirms deleting the Bybit key
- THEN the panel shows that the key cannot be deleted while Bybit has an enabled strategy, and Bybit's entry still shows its active key

#### Scenario: A confirmed, successful delete clears the exchange's entry

- GIVEN Bybit has an active key, every strategy bound to its pool is disabled, and none holds an open position
- WHEN the owner confirms deleting the Bybit key
- THEN Bybit's entry shows the same empty state as an exchange with no key, and an "Add key" control

### Requirement: Every Panel String Is Localized EN/ES

Every user-facing string in the panel MUST be resolved through the existing
i18n mechanism (English and Spanish) and MUST NOT be hardcoded display text.

#### Scenario: Every view renders under both locales

- GIVEN the locale is set to English
- WHEN any panel view renders
- THEN every visible string is in English, sourced from i18n

- GIVEN the locale is set to Spanish
- WHEN the same view renders
- THEN every visible string is in Spanish, sourced from i18n, with no leftover hardcoded English text

### Requirement: Empty States Everywhere Data May Be Absent

Every view or panel section whose data may legitimately be empty (a fresh
strategy with no closed trades, an empty ledger under `DRY_RUN`, no pending
bookings, an exchange with no key) MUST render a defined empty state rather
than a blank area or an error.

#### Scenario: A strategy with no trades shows empty stats, not an error

- GIVEN a newly created strategy with no closed trades
- WHEN its detail view renders its stats section
- THEN a defined empty state is shown, with no error

### Requirement: Admin-Gated Views Require the Bearer Token

Every panel view that reads or writes through `/api` MUST be gated behind the
existing admin token entry mechanism, consistent with how the bookings view
is gated today.

#### Scenario: An ungated session cannot load panel data

- GIVEN no admin token has been entered in the current session
- WHEN a gated view attempts to load its data
- THEN the request is refused and the panel prompts for the token rather than showing partial data
