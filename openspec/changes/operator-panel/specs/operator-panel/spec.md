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
>
> **Revised 2026-10-02 (owner decisions 40 and 41).** Allowed pairs are chosen
> from the pool's available pairs through a searchable selector; the free-text
> pairs input is removed. New requirement: "Allowed Pairs Are Chosen From The
> Pool's Available Pairs".
>
> **Revised 2026-10-02 (owner decision 42).** The strategy detail view gains a
> delete control for a strategy with no history. New requirement: "Deleting A
> Strategy Requires Explicit Confirmation And States Its Refusal", placed after
> "Archive Requires Explicit Confirmation".
>
> **Revised 2026-10-04 (owner decisions 43, 44 and 45, design addendum
> "decision 43").** The strategy detail view lists the strategy's closed
> operations with their prices, size and fees, marks dry-run operations by how
> they were filled, pages 20 at a time on a click, and opens each operation in a
> detail dialog with its fills. Six requirements are added after "Strategy
> Detail Shows Stats, Uptime, and Lifecycle Controls", which gains one sentence
> pointing to them, and "Every Panel String Is Localized EN/ES" gains one
> scenario.
>
> **Revised 2026-10-06 (owner decisions 44 and 48, design addendum "unit
> 12f").** The strategy detail view gains the share of the pool per trade (a
> field above a track, saved through an explicit Save button, with the amount it
> asks for served by the server and two information buttons), a "Saved" button text
> after a save, two Copy buttons, the full webhook URL with its host, and a win
> rate in "By pair". Fifteen requirements are added after "Copy-Ready Webhook
> Message, Secret Revealed Only On Explicit Request"; "Strategy Detail Shows
> Stats, Uptime, and Lifecycle Controls" and that webhook requirement each gain
> one sentence pointing to them, and "Every Panel String Is Localized EN/ES"
> gains one scenario.
>
> **Revised 2026-10-10 (owner decisions 54 to 59, design addendum "Settings,
> the exchange keys (PR 13)").** Settings was designed again and the September
> requirements about it are replaced, not amended. The three requirements
> "Settings Manages One Key Per Exchange", "Settings Shows the Validation
> Outcome On Add/Replace" and "Settings Allows Deleting a Key, With Explicit
> Confirmation and a Stated Refusal" are replaced by the group that starts at
> "Settings Reads Two Existing Routes And Changes No API". "Shared Layout Shell"
> gains the tab marks by pointing to "The Exchange Tabs Carry The Key State".
> No API changes. This capability had not been merged to `openspec/specs/` when
> this revision was written, so the replacement is in place.
>
> **Revised 2026-10-12 (owner decision 65, design addendum "open positions, a
> mark and a list read from the ledger" §§ H and I; visual reference
> `visual/project/OpenPositions.html`, approved at commit `6603dea`).** The
> panel shows open positions and orders in flight read from the ledger: a mark
> on each row of the Strategies list with three labelled figures of the selected
> exchange above it, a section "Open positions" above the closed trades on the
> strategy detail page, a list pool by pool and a count on the Overview, and the
> top bar's "Live" badge in the `gain` colour. Twenty-two requirements are added
> after "Strategy Detail Shows Stats, Uptime, and Lifecycle Controls";
> "Shared Layout Shell", "Overview Shows Balance, PnL Ranges, Curve, and Monthly
> Grid", "Strategies List Excludes Archived By Default" and "Strategy Detail
> Shows Stats, Uptime, and Lifecycle Controls" each gain a sentence pointing to
> them, and "Every Panel String Is Localized EN/ES" gains one scenario. The data
> is served by `GET /api/positions/open` (admin-api). Four owner questions of the
> addendum (section O, Q6 to Q9) were answered by the owner on 2026-10-13, each
> as its default; every requirement or scenario that depends on one carries a
> note "decided by the owner on 2026-10-13 (Qn)". Nothing is pending.

## Requirements

### Requirement: Shared Layout Shell

The panel MUST present a shared layout shell consisting of a top bar, a
sidebar navigation for Overview, Strategies, Discrepancies, and Settings, in
that order, on wide viewports, and the same navigation as a bottom bar on small
viewports (revised 2026-10-16, owner decision 66: a fourth item, with a badge,
as "The Navigation Has A Fourth Item, Discrepancies, With A Badge Of What Needs
The Owner" states). The top bar MUST
carry exchange selection on the exchange-scoped views (Overview, Strategies).
Settings is not exchange-scoped: it lists every exchange and its top bar
carries no exchange selection (Settings.dc.html). The exchange selection
MUST carry each exchange's key mark as "The Exchange Tabs Carry The Key State"
states it (revised 2026-10-10, decisions 20, 22, 55 and 59). The top bar's mode
badge MUST read "Live" in the `gain` colour, as "The Top Bar's Live Badge Is
Drawn In The Gain Colour" states (revised 2026-10-12, decision 65).

(Previously: no mention of the badge's colour.)

#### Scenario: A keyless (DEGRADED) exchange is marked in the exchange bar

> **Added 2026-09-25 (owner decision 20).**

- GIVEN Binance has an enabled pool and no active credential, and Bybit has a trade-capable one
- WHEN the exchange bar renders
- THEN Binance is marked "no key" in amber, and Bybit is not marked
- AND the full rule, including the grey "no key" of a deleted key, is in "The Exchange Tabs Carry The Key State"

#### Scenario: Sidebar navigation on a wide viewport

- GIVEN the panel is open on a wide viewport
- WHEN the shell renders
- THEN Overview, Strategies, Discrepancies, and Settings are reachable from a sidebar, in that order

#### Scenario: Bottom bar navigation on a small viewport

- GIVEN the panel is open on a small viewport
- WHEN the shell renders
- THEN Overview, Strategies, Discrepancies, and Settings are reachable from a bottom bar instead of a sidebar, in four cells

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
with drawdown from previous peak, and the monthly grid. It MUST also list
every open position of the selected exchange, pool by pool, and its monthly
summary MUST count them as "N open, M of them dry run", as "The Overview Lists
Every Open Position Of The Selected Exchange, Pool By Pool" and "The Overview's
Count Says How Many Are Open And How Many Of Them Are Dry Run" state (added
2026-10-12, owner decision 65).

(Previously: no mention of open positions.)

#### Scenario: Overview renders all required elements for a pool with data

- GIVEN pool `(bybit, usdt-m, USDT)` has closed trades
- WHEN Overview renders for Bybit
- THEN available balance, all five PnL ranges, the compounded curve with drawdown, and the monthly grid are shown for that pool

#### Scenario: Overview renders empty states under DRY_RUN

- GIVEN `DRY_RUN=true` and the ledger is empty
- WHEN Overview renders
- THEN it shows a defined empty state for the curve, monthly grid, and PnL ranges, with no error

### Requirement: The Overview Has No Decision Rail And Carries Its Own Scope Messages

> **Replaces, on 2026-10-16, the requirement "Pending-Bookings Panel On Overview" (owner decision 66, "Needs your decision leaves the Overview"; design addendum "PR 15" § H; prototype examples 12 and 13).**

(Previously: the Overview MUST show a pending-bookings panel, the "Needs your decision" rail, beside the dashboard on wide viewports and between the return chart and the monthly grid on a phone, reflecting only the selected exchange's bookings. With automatic booking nothing is pending for a human, and the rail would always be empty.)

The Overview MUST NOT draw the decision rail or its slot, on any width: no column beside the pool panels from `xl`, and nothing between the return chart and the month grid. The pool panels MUST take the whole width. The three states of the exchange scope that the rail also carried MUST move into the Overview page, drawn where the panels would be, under the title, with the same roles and look: loading (`role="status"`, ink-3), failed (`role="alert"`, a box with a red border) and no exchanges (ink-3). Their texts are reworded, because they spoke of pending bookings:

- loading: "Loading exchanges…" / "Cargando exchanges…" (the English is the unchanged existing text);
- failed: "The pools are hidden because the exchanges could not be loaded, so they cannot be filtered." / "Los pools están ocultos porque no se pudieron cargar los exchanges y no se pueden filtrar.";
- none: "No exchange is configured, so there are no pools to show." / "No hay ningún exchange configurado, por lo que no hay pools que mostrar.".

The `betweenChartAndGrid` prop of `PoolPanel` MUST be removed, since nothing else passes it. The keys `overview.decisionRail.*` MUST be deleted, except that the three messages MUST live under `overview.scope.*` in both locales.

#### Scenario: No rail on a wide viewport

- GIVEN the Overview on a wide viewport
- WHEN it renders
- THEN no "Needs your decision" rail and no column beside the pool panels is drawn, and the panels take the whole width

#### Scenario: No rail between the chart and the grid on a phone

- GIVEN the Overview on a phone viewport
- WHEN it renders
- THEN nothing sits between the return chart and the month grid, and the positions are cards under the grid

#### Scenario: The scope is loading

- GIVEN the exchanges are still loading
- WHEN the Overview renders
- THEN a `role="status"` message "Loading exchanges…" in ink-3 is drawn under the title where the panels would be

#### Scenario: The scope failed

- GIVEN the exchanges failed to load
- WHEN the Overview renders
- THEN a `role="alert"` box with a red border reads "The pools are hidden because the exchanges could not be loaded, so they cannot be filtered." and the page is not left with its title alone

#### Scenario: No exchange is configured

- GIVEN the exchanges loaded and the list is empty
- WHEN the Overview renders
- THEN "No exchange is configured, so there are no pools to show." is drawn in ink-3

#### Scenario: The three messages exist in Spanish

- GIVEN the language is Spanish
- WHEN each of the three states renders
- THEN it reads the Spanish text above, exactly

### Requirement: Strategies List Excludes Archived By Default

The Strategies list view MUST exclude archived strategies by default and
MUST show each listed strategy's enabled state. It MUST also carry a mark on
each row for the positions and orders in flight that strategy holds, and the
three labelled figures of the selected exchange above the list, as the
requirements added after "Strategy Detail Shows Stats, Uptime, and Lifecycle
Controls" for open positions state (added 2026-10-12, owner decision 65). A
disabled strategy that holds a position keeps its mark.

(Previously: no mention of open positions.)

#### Scenario: Archived strategy is absent from the default list

- GIVEN strategy S1 is archived
- WHEN the Strategies list renders with default filters
- THEN S1 does not appear

### Requirement: Strategy Detail Shows Stats, Uptime, and Lifecycle Controls

The strategy detail view MUST show the strategy's performance stats (PnL,
trade count, stats by pair), its cumulative uptime as "active X days" with
the first activation date, its allowed-pairs list with an edit control, and
enable/disable and archive controls. It also carries the delete control of
"Deleting A Strategy Requires Explicit Confirmation And States Its Refusal"
(added 2026-10-02, owner decision 42). It also lists the strategy's closed
operations, as the six requirements that follow this one describe (added
2026-10-04, owner decision 43). Its settings column MUST carry the share of the
pool per trade, and its stats by pair MUST include a win rate, as the
requirements added for unit 12f describe (unit 12f, 2026-10-06, owner decisions
44 and 48).

It also lists the strategy's open positions, in a section above the closed
trades, as the requirements that follow this one state (added 2026-10-12, owner
decision 65). (Previously: no mention of open positions.)

(Previously: no mention of the operations list, which the requirements below
now specify. Previously: no mention of the share of the pool per trade or of the
win rate by pair.)

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

### Requirement: The Panel Reads Every Open Position From One Answer

> **Added 2026-10-12 (owner decision 65; design addendum "open positions" § F and § H, "The data").**

Every place of the panel that shows an open position or an order in flight (the
row marks and the figures of the Strategies page, the section of the strategy
detail page, and the Overview's list and count) MUST be a selection from ONE
answer of `GET /api/positions/open`, held in one query cache under one key, and
MUST NOT make a request of its own per row or per page. The answer MUST be
considered stale after 60 seconds, MUST be read again every 60 seconds, and MUST
be read again when the browser tab is looked at again after going stale. It
MUST be read again after a booking is approved or rejected and when the owner
presses "Read again"; it MUST NOT be read again by the enable switch, a change
of a share or an archive, none of which opens or closes anything. Selecting a
different exchange MUST select again from the answer already held and MUST NOT
make a request.

The panel MUST check the shape of every element. A body that is not that shape
MUST be an error and never an empty list, and a 404 (an API that predates the
route) MUST be a failure and never "no report". A pool whose `exchange`,
`venue` or `settlement_currency` is missing or empty MUST refuse the whole
answer, so that a position no tab can claim is an error on screen and never a
row that silently belongs nowhere. A null in `opened_at`, `fees`,
`margin_granted` or `leverage` MUST be accepted, and a missing field MUST be
refused. The browser MUST compute no sum of money from this answer: the only
counts it draws are numbers of positions.

#### Scenario: Three places, one request

- GIVEN the Strategies page with six rows, and then the Overview, are opened in one session
- WHEN the network is read
- THEN `GET /api/positions/open` was requested once for the page and not once per row, and the Overview's list used the answer already held

#### Scenario: A change of exchange asks the server nothing

- GIVEN the Strategies page shows Bybit with the answer read
- WHEN the owner selects Binance
- THEN the page draws Binance's marks and figures and no request was made

#### Scenario: The answer is read again every 60 seconds and when the tab is looked at again

- GIVEN the answer was read and 60 seconds pass
- WHEN the interval elapses, and in a second case the browser tab is focused after the answer went stale
- THEN the route is requested again in each case

#### Scenario: A booking decision reads it again, and a switch does not

- GIVEN the answer is held
- WHEN a booking is approved, then rejected, then a strategy is enabled, a share is saved and a strategy is archived
- THEN the route is requested again after the approval and after the rejection and after none of the other three

#### Scenario: "Read again" asks now

- GIVEN the figures are shown
- WHEN the owner presses "Read again"
- THEN the route is requested at once

#### Scenario: A malformed body is an error

- GIVEN the route answers 200 with a position that has no `allocation_id`
- WHEN the panel reads it
- THEN the open-state views show their error state and none shows an empty list

#### Scenario: A 404 is a failure

- GIVEN an API that answers 404 for the route
- WHEN the panel reads it
- THEN the views show their error state, not "No open position."

#### Scenario: An element with an empty pool value refuses the answer

- GIVEN one element whose `pool.exchange` is an empty string
- WHEN the panel reads it
- THEN the whole answer is refused and the views show their error state

#### Scenario: A position the facts could not decorate is accepted

- GIVEN a position with `opened_at`, `fees`, `margin_granted` and `leverage` null
- WHEN the panel reads it
- THEN the answer is accepted and the position is drawn

### Requirement: The Marks Follow One Rule: The Shape Says What It Is, The Colour Says The Origin, Red Says Something Is Wrong

> **Added 2026-10-12 (owner decision 65, bullets of 2026-10-12; design addendum "open positions" § H, "The marks: one rule"; prototype key "Reading the marks").**

Every mark of the panel for an open position or an order in flight MUST follow
one rule. A FILLED mark is a position; a DASHED, UNFILLED mark is an order in
flight, and dashed MUST mean nothing else. The colour MUST say the origin:
amber (the palette's `decision` token, as the mode badge) for dry run, and
cyan (the `gain` token, as the "Live" badge) for live. Red (`loss`) MUST mean
one thing, that something is wrong and needs the owner, and MUST always be
beside its words. No mark MUST say a result: `LONG` and `SHORT` stay in ink,
and a mark holds no number. Each mark MUST say its origin as a WORD, never by
colour or shape alone. Marks MUST use only the palette's tokens, no hex colour
and no `var()` in a class.

| Mark | Fill | Border | Words |
| --- | --- | --- | --- |
| Position, dry run | filled | solid amber | pair and side in ink, "Dry run" in amber |
| Position, live | filled | solid cyan | pair and side in ink, "Live" in cyan |
| Position holding fills of both origins | filled | solid red | pair and side in ink, "Dry run and live" in red |
| Position, origin unknown | filled | solid neutral | "origin unknown" in the faint ink |
| Order in flight, dry run | unfilled | dashed amber | pair and "order in flight" in ink, "Dry run" in amber |
| Order in flight, live | unfilled | dashed cyan | the same, "Live" in cyan |
| Order in flight, origin unknown | unfilled | dashed neutral | the same, "origin unknown" in the faint ink |
| Venue disagrees | unfilled | solid red | "Venue disagrees" in red |

A position's chip MUST read its pair, then `LONG` or `SHORT` (or "side not
readable" when the side is null), then the origin. An order's chip MUST read its
pair, "order in flight" and the origin; whether it opens or closes is on its
line on the detail page, not on the chip. Parts of a mark MUST be separated by
` · ` in the faint ink. The "unknown origin" position is drawn by the key and no
answer produces it today, since a position's origin is one of three values.

#### Scenario: A live position is filled, solid and cyan

- GIVEN a live position on `AAVEUSDT`, side `LONG`
- WHEN its mark renders
- THEN it reads `AAVEUSDT · LONG · Live`, filled, with a solid cyan border and "Live" in cyan

#### Scenario: A dry-run position is amber

- GIVEN a rehearsal position on `SFPUSDT`, side `SHORT`
- WHEN its mark renders
- THEN it reads `SFPUSDT · SHORT · Dry run`, filled, with a solid amber border and "Dry run" in amber

#### Scenario: A position of both origins is red, with its words

- GIVEN a position with origin `mixed` on `STXUSDT`, side `LONG`
- WHEN its mark renders
- THEN it reads `STXUSDT · LONG · Dry run and live` with a solid red border and "Dry run and live" in red

#### Scenario: Dashed is an order in flight and nothing else

- GIVEN one order in flight of each origin, and positions of every origin
- WHEN every mark renders
- THEN the three orders have a dashed border, unfilled, and no position, no venue mark and no other element of the open-position views has a dashed border

#### Scenario: An order of unknown origin is dashed and neutral

- GIVEN an order in flight whose origin is `unknown`
- WHEN its mark renders
- THEN it reads `SFPUSDT · order in flight · origin unknown`, dashed, with a neutral border and the words in the faint ink

#### Scenario: A position whose origin is unknown has a solid neutral border

- GIVEN a position mark of origin unknown, as the prototype's key draws it
- WHEN it renders
- THEN its border is solid and neutral and it reads "origin unknown"

#### Scenario: Red appears only with its words

- GIVEN a position of both origins, a position the venue disagrees on and a failed read
- WHEN each renders
- THEN each red element is beside its words ("Dry run and live", "Venue disagrees", the error sentence), and no red element is without text

#### Scenario: No mark says a result

- GIVEN positions of every side and origin
- WHEN their marks render
- THEN `LONG` and `SHORT` are in the ink colour, neither in the gain nor the loss colour, and no mark holds a number

#### Scenario: Only palette tokens

- GIVEN the open-position components
- WHEN their source is read
- THEN no class holds a hex colour or a `var()`, and no inline style is used

### Requirement: A Strategy's Row Carries A Mark For Each Position And Each Order It Holds

> **Added 2026-10-12 (owner decision 65, the third question and bullets of 2026-10-12; design addendum "open positions" § H, "The marks" and "Every state"; prototype examples 2 to 9 and 12).**

Each row of the Strategies list MUST carry one chip per open position and per
order in flight of THAT strategy ON THAT STRATEGY'S EXCHANGE, whatever its
origin, and nothing at all when there is none. The chips MUST follow the rule of
"The Marks Follow One Rule" and MUST NOT depend on whether the strategy is
enabled: a DISABLED strategy that holds a position shows it like any other. A
position's venue chip, when the reconciliation has confirmed a disagreement,
MUST follow that position's chip. From `lg` the chips MUST sit in the row's
second grid row, in its first track only, so that the row's figures and its
switch stay where they are; below `lg` they MUST be the row's last full-width
line, and a long pair MUST NOT make the row wider than a phone. The list of a
row's marks MUST be named "Open positions of {name}". While the answer is
loading a row MUST draw a decorative placeholder whose accessible name is
"Reading open positions…"; when the first read failed a row MUST draw nothing
and the line above the list MUST say why a row without a mark does not mean that
nothing is open.

#### Scenario: A row with one live position

- GIVEN strategy S1 on Bybit holds a live `AAVEUSDT` position and the selected exchange is Bybit
- WHEN the Strategies list renders
- THEN S1's row carries one chip, `AAVEUSDT · LONG · Live`

#### Scenario: A row with a rehearsal position

- GIVEN S1 holds a rehearsal `SFPUSDT` SHORT
- WHEN the list renders
- THEN its chip reads `SFPUSDT · SHORT · Dry run`

#### Scenario: A position whose symbol cannot be resolved

- GIVEN S1 holds a position with `figures_missing` `UNRESOLVED_SYMBOL` on `XYZBTC`, live
- WHEN the list renders
- THEN its chip reads `XYZBTC · side not readable · Live`

#### Scenario: Three orders in flight, each of one origin

- GIVEN three strategies each with an order in flight on `SFPUSDT`: one dry run, one live, one with no order id
- WHEN the list renders
- THEN each row carries a dashed, unfilled chip reading `SFPUSDT · order in flight · Dry run`, `... · Live` and `... · origin unknown`

#### Scenario: A disabled strategy holding a position shows it

- GIVEN strategy S1 is disabled and holds a position
- WHEN the list renders
- THEN S1's row carries the chip, beside its switch in the off position

#### Scenario: Several positions wrap in their own grid row

- GIVEN S1 holds three positions on three pairs and S2 holds none
- WHEN the list renders at a wide viewport
- THEN S1's three chips wrap in their own grid row, and S1's figures and switch sit at the same height as S2's

#### Scenario: A row with nothing open has no mark

- GIVEN S3 holds nothing
- WHEN the list renders
- THEN S3's row has no mark and no empty element

#### Scenario: A position of another strategy is not on this row

- GIVEN S1 holds a position and S2 holds none
- WHEN the list renders
- THEN S2's row carries no chip

#### Scenario: Chips are the last line on a phone

- GIVEN a phone viewport of 390 px and S1 with a long pair
- WHEN the list renders
- THEN the chips are the row's last full-width line and the row is not wider than the viewport

#### Scenario: While the answer loads a row shows a placeholder with a name

- GIVEN the positions answer has not arrived
- WHEN the list renders
- THEN each row shows a decorative "…" and its accessible name is "Reading open positions…"

#### Scenario: When the first read failed a row draws nothing

- GIVEN the first read of the answer failed
- WHEN the list renders
- THEN no row draws a mark and the line above the list reads "Open positions could not be read. A row without a mark does not mean that nothing is open."

### Requirement: The Venue Mark Reads The Confirmed Discrepancies, Says What Is Happening To It, And Leads To Its Item

> **Revised 2026-10-16 (owner decision 66 and its Q8; design addendum "PR 15" § H; prototype examples 14 to 16). Added 2026-10-12 as "The Venue Mark Leads To The Pending Decision, Or Says That No Booking Is Proposed" (owner decision 65).**

(Previously: the chip was followed by the link "See the pending decision", leading to the Overview's rail `/#decision-rail`, or by the words "No booking is proposed for it." and no link, from the pending proposals. Proposals no longer exist for a human, so both the link and the words are replaced, and the chip reads the confirmed discrepancies instead of the proposals.)

When a position carries a `venue_disagreement`, its row MUST show a second chip, "Venue disagrees", directly after that position's chip, and the chip MUST stay red in every state below, because the row still shows open a position the venue no longer holds. The chip and the venue line MUST find their discrepancy by the `discrepancy_id` of the position's `venue_disagreement` in the lists `being_booked` or `needs_owner` of the one query `useConfirmedDiscrepancies`. Then, after the chip, ONE of three things:

- the id is in `being_booked`: the words "being booked automatically" (owner decision 66, Q8). When the booking lands, the position leaves the list;
- the id is in `needs_owner`: the words of its reason ("could not be booked automatically" for `NOT_BOOKED`, "one booking cannot split it" for `SEVERAL_ALLOCATIONS`, "which strategy it reduced cannot be told" for `AMBIGUOUS_PARTIAL_REDUCE`), and the mark is already red, so nothing else changes when the discrepancy starts counting in the badge;
- while the query is loading, after it failed, or when the id is in neither list (for instance one the scan resolved between the two reads): no claim and no link, only the red chip or line and its nets. PR 14's rule "until it is read, neither the link nor the words" stays, applied to this query.

When the id is found in either list, the link "See the discrepancy" MUST be drawn; it MUST lead to `/discrepancies` with the hash `#discrepancy-<discrepancy_id>`. The chip, and its words and link, MUST wrap together as one group. The link MUST be a real link whose accessible name is "See the discrepancy, {pair}". The chip and the line MUST read no booking proposal.

#### Scenario: A booking under way says so and links to its item

- GIVEN position A1 carries a disagreement whose id is in `being_booked`
- WHEN the row renders
- THEN the chip "Venue disagrees" is red, follows A1's chip, and is followed by "being booked automatically" and the link "See the discrepancy" leading to `/discrepancies#discrepancy-<id>`

#### Scenario: A discrepancy that needs the owner says why

- GIVEN position A1 carries a disagreement whose id is in `needs_owner` with the reason `NOT_BOOKED`
- WHEN the row renders
- THEN the chip is followed by "could not be booked automatically" and the link "See the discrepancy"

#### Scenario: While the query loads, no claim is made

- GIVEN position A1 carries a disagreement and the confirmed-discrepancies query is still loading
- WHEN the row renders
- THEN the chip is drawn red with neither the words nor the link

#### Scenario: When the query failed, no claim is made

- GIVEN position A1 carries a disagreement and the query failed
- WHEN the row renders
- THEN the chip is drawn red with neither the words nor the link

#### Scenario: An id in neither list makes no claim

- GIVEN position A1 carries a disagreement whose id is in neither list
- WHEN the row renders
- THEN the chip is drawn red with neither the words nor the link

#### Scenario: No proposal is read

- GIVEN the chip and the line
- WHEN their network requests are read
- THEN none is a request for booking proposals

#### Scenario: The group wraps together

- GIVEN the chip and its link at a narrow width
- WHEN the row renders
- THEN the chip and its follow-up wrap as one group

#### Scenario: The link leads to the item and brings it into view

- GIVEN the link is followed from the Strategies page
- WHEN the Discrepancies page mounts with the hash `#discrepancy-<id>`
- THEN the item with that id is scrolled into view

#### Scenario: A hash change on the page scrolls again

- GIVEN the Discrepancies page is on screen and scrolled away from the item
- WHEN the location's hash changes to `#discrepancy-<id>`
- THEN the item is scrolled into view

#### Scenario: A rehearsal position carries no mark in practice

- GIVEN a rehearsal position and no discrepancy naming it
- WHEN the row renders
- THEN it has no venue chip

### Requirement: The Strategies Page Shows Three Labelled Figures For The Selected Exchange Only

> **Added 2026-10-12 (owner decision 65, bullets of 2026-10-12; design addendum "open positions" § H, "The summary: OpenStateLine"; prototype examples 1 to 12).**

Between the title row and the list, the Strategies page MUST show three labelled
figures of the SELECTED exchange, in this form: `Open: 2 · Orders in flight: 1 ·
Last read: 21:40:03 UTC`. "Open" MUST be the number of positions whose
`pool.exchange` is the selected one, "Orders in flight" the number of its orders,
and "Last read" the answer's `as_of` with hours, minutes and seconds. They MUST
count what the exchange holds and not what the list shows: a position of an
archived strategy is in "Open". The figures MUST name no exchange, since the
selected tab does. Each label is followed by a colon, and a ` · ` in the faint
ink separates two figures; below the `sm` width the figures MUST wrap and no
separator be drawn, so that none starts a line. A bordered button "Read again",
44 px tall, MUST ask for the answer at once. The two counts and the lines under
them MUST sit in one live region (`role="status"`); "Last read" MUST sit on the
same visual line and OUTSIDE that region, so that a time which changes every
minute is not announced for a state that did not.

Before the scope is known, or when no exchange exists, the figures MUST NOT be
drawn and MUST NOT ask for anything: the page's own text already says why the
list is absent.

#### Scenario: Nothing open on the selected exchange

- GIVEN the answer holds nothing whose exchange is the selected one, read at 21:40:03
- WHEN the Strategies page renders
- THEN it shows `Open: 0 · Orders in flight: 0 · Last read: 21:40:03 UTC` and the "Read again" button

#### Scenario: The counts are the exchange's, with a position of an archived strategy counted

- GIVEN the selected exchange holds two positions, one of an archived strategy hidden from the list, and one order in flight
- WHEN the page renders
- THEN it shows `Open: 2 · Orders in flight: 1`

#### Scenario: Orders count apart from positions

- GIVEN the selected exchange holds three orders in flight and no position
- WHEN the page renders
- THEN it shows `Open: 0 · Orders in flight: 3`

#### Scenario: The figures name no exchange

- GIVEN any state
- WHEN the figures render
- THEN none of the three labels or values contains an exchange's name

#### Scenario: The time has seconds and UTC

- GIVEN `as_of` is 21:40:03 UTC
- WHEN the figures render
- THEN "Last read" reads `21:40:03 UTC`

#### Scenario: The live region holds the counts and not the time

- GIVEN the figures are drawn
- WHEN the markup is read
- THEN the two counts are inside an element with `role="status"` and the "Last read" figure is not

#### Scenario: Below the sm width the figures wrap without separators

- GIVEN a phone viewport
- WHEN the figures render
- THEN they wrap, no ` · ` is drawn between them, and the button is 44 px tall

#### Scenario: The scope is not known

- GIVEN the pools have not been read, or no exchange exists
- WHEN the page renders
- THEN the figures are not drawn and no request for positions is made on their account

#### Scenario: "Read again" asks now

- GIVEN the figures are drawn
- WHEN the owner presses "Read again"
- THEN the route is requested at once

### Requirement: "Not On This List" Names Only What The Selected Exchange Holds And Its List Does Not Show

> **Added 2026-10-12 (owner decision 65, bullets of 2026-10-12; design addendum "open positions" § H, "The summary"; prototype examples 10, 12d and 26a).**

Under the figures, when the selected exchange holds a position or an order that
no row on screen carries, the page MUST add a second line "Not on this list:
{items}." and MUST name only what THAT exchange holds. It MUST name: a position
or an order of an archived strategy while archived strategies are hidden; one
that could not be matched to a strategy (its strategy id is null); and, by the
same rule, every element of the exchange when the strategies list failed to
load. One item MUST be these parts joined by ` · ` in this order: the strategy's
name; "archived" when the strategy is; the pair (the element's market keys,
joined by ` / ` when several); "order in flight" for an order; the origin's
word; and "figures not readable" for a position whose figures are missing. Items
MUST be joined by `; `, positions first, then orders, each in the answer's
order. An element MUST NOT be matched to a row by its name, only by its strategy
id. While the strategies list is loading the line MUST be withheld, since every
element would otherwise be named for an instant and then move to its row; the
figures MUST be drawn all the same. The line MUST be drawn only when there is
something to name.

#### Scenario: Two positions on no row, one order on a row

- GIVEN the selected exchange holds an archived strategy's rehearsal position on `LINKUSDT`, a position with no strategy id on `XYZBTC` (live, figures missing), and an order on a row of the page
- WHEN the page renders
- THEN it shows `Open: 2 · Orders in flight: 1` and "Not on this list: LINK 4h - RSI Divergences · archived · LINKUSDT · Dry run; STX 4h - RSI Divergences · XYZBTC · Live · figures not readable."

#### Scenario: A position with no strategy id is named on its own exchange's tab

- GIVEN an undecorated position of the selected exchange, with a null strategy id
- WHEN the page renders
- THEN it is counted in "Open" and named under the figures, and no row carries a chip for it

#### Scenario: An order is named by the chip's own words

- GIVEN an order in flight of an archived strategy on `SFPUSDT`, live
- WHEN the page renders
- THEN the line names it as `{name} · archived · SFPUSDT · order in flight · Live`

#### Scenario: Positions come before orders

- GIVEN one order and one position, both on no row
- WHEN the line renders
- THEN the position is the first item and the order the second

#### Scenario: Nothing to name draws no line

- GIVEN every element of the selected exchange is carried by a row
- WHEN the page renders
- THEN no "Not on this list" line is drawn

#### Scenario: The line is withheld while the strategies load

- GIVEN the strategies list is still loading and the exchange holds an element
- WHEN the page renders
- THEN the figures are drawn and the "Not on this list" line is not

#### Scenario: When the strategies list failed, every element of the exchange is named

- GIVEN the strategies list failed to load and the exchange holds two positions
- WHEN the page renders
- THEN `Open: 2` is drawn and "Not on this list" names both

#### Scenario: Another exchange is never named

- GIVEN Binance is selected and Bybit holds an archived strategy's position
- WHEN the page renders
- THEN no item, count or word of Bybit is drawn

### Requirement: The Open-State Figures Never Read As Zero When They Are Not Known

> **Added 2026-10-12 (owner decision 65; design addendum "open positions" § H, "Every state"; prototype examples 11a to 11d).**

The figures MUST show each of these states, and no failed or pending state MUST
read as zero open.

- Loading, nothing read yet: the text "Reading open positions…" in a
  `role="status"` element, in the faint ink, with no button.
- The first read failed: the sentence "Open positions could not be read. A row
  without a mark does not mean that nothing is open." in a `role="alert"` element
  in red, with "Read again". The failure MUST be shown only after the query
  client has retried and given up; until then the loading state is shown.
- Reading again after a failed first read (added 2026-10-13, after the final
  review): the "Read again" button MUST stay in the document, in the same place
  and with the focus, marked `aria-disabled="true"` (not `disabled`) and ignoring
  presses, beside the loading text. It MUST be drawn only after a read has failed,
  never on a first load.
- A refresh failed after a good read: the LAST figures MUST be kept, "Last read"
  MUST still be the last good answer's time, and "Could not be refreshed since
  {time} UTC." MUST be added in red as the last line. This holds also when the
  last good answer was empty.
- Nothing open on the selected exchange: `Open: 0 · Orders in flight: 0 · Last
  read: {time} UTC`, drawn only from a successful read that holds no element of
  that exchange.

#### Scenario: Loading

- GIVEN the answer has not arrived
- WHEN the page renders
- THEN it shows "Reading open positions…" with `role="status"`, no button, and no figure

#### Scenario: The first read fails

- GIVEN the first read failed after its retries
- WHEN the page renders
- THEN the red sentence is drawn with `role="alert"` and "Read again", and neither `Open: 0` nor any figure is drawn

#### Scenario: "Read again" stays in place while the panel reads again after a failed first read

- GIVEN the first read failed, the red sentence and "Read again" are drawn, and the button has the focus
- WHEN the button is pressed
- THEN the same button is still in the document, it still has the focus and it is marked `aria-disabled="true"`, beside "Reading open positions…" with `role="status"`
- AND pressing it again starts no second request
- AND when the read succeeds the content is drawn and the button is gone, and when it fails again the red sentence and the enabled button are drawn again

#### Scenario: The retries are not an error yet

- GIVEN the first read has failed once and is being retried
- WHEN the page renders
- THEN the loading text is shown and the error sentence is not

#### Scenario: A refresh fails after a good read

- GIVEN a good read at 21:38:12 holding two positions, and a later refresh fails
- WHEN the page renders
- THEN `Open: 2` and `Last read: 21:38:12 UTC` are kept, and the red line "Could not be refreshed since 21:38:12 UTC." is the last line

#### Scenario: A refresh fails after an empty read

- GIVEN a good read at 21:38:12 that held nothing, and a later refresh fails
- WHEN the page renders
- THEN `Open: 0 · Orders in flight: 0 · Last read: 21:38:12 UTC` is kept and the red line is added, so that the zero is not read as current

#### Scenario: Zero is drawn only after a successful read

- GIVEN a successful read that holds nothing of the selected exchange
- WHEN the page renders
- THEN `Open: 0 · Orders in flight: 0` is drawn

### Requirement: The Strategies Page Shows Nothing Of Another Exchange

> **Added 2026-10-12 (owner decision 65, bullets of 2026-10-12, superseding the scope of the Q4 sentence; design addendum "open positions" § B and § H, "The scope rule").**

Everything the Strategies page draws about open positions MUST be selected from
the elements whose `pool.exchange` is the selected tab's, and from nothing else:
the two counts are the lengths of that selection; a row's marks are the
selection of its strategy's elements inside its strategy's exchange; and the
"Not on this list" line is what that selection holds and no row carries. No
pair, name, count or word of another exchange MUST reach the page. Changing the
tab MUST select again from the answer already held. The count "Open" MUST always
equal the position chips on screen plus the positions named under the figures.
No text of the panel MUST say that nothing is open anywhere, and none MUST be
worded as a permission to change the mode: the panel is the view, and the
worker's start is what refuses a mode that cannot close what the ledger holds.

An element whose exchange is no tab at all (stored data at fault) belongs to NO
tab. Its strategy's detail page MUST show it when it has a strategy id, because
that page selects by id.

> **Decided by the owner on 2026-10-13 (Q7): say nothing.** No line says that
> such an item exists. An element with no strategy id and no tab (a position the
> facts could not decorate, or an undecorated order, on an exchange without a
> tab) is drawn by NO page of the panel; its only trace is the server's WARNING.
> A count-only line under the figures was proposed and declined.

#### Scenario: The other exchange's elements are absent

- GIVEN Bybit is selected and the answer holds a position and an order on Binance
- WHEN the Strategies page renders
- THEN `Open` and `Orders in flight` count none of them, no row carries them, and "Not on this list" does not name them

#### Scenario: Switching the tab selects again

- GIVEN Bybit holds one position and Binance holds two
- WHEN the owner selects Binance
- THEN the page reads `Open: 2` and Bybit's position is nowhere on it

#### Scenario: A strategy whose position sits in another exchange's pool

- GIVEN strategy S1 of Bybit has a position whose pool names Binance (a stored fault)
- WHEN the page renders for Bybit, and then for Binance
- THEN on Bybit the position is not on S1's row and is not counted; on Binance it is counted and named under the figures because S1 has no row there

#### Scenario: The count equals the chips plus the named

- GIVEN the selected exchange holds four positions: two on rows, one of an archived strategy and one with no strategy id
- WHEN the page renders
- THEN `Open: 4`, two chips and two named items

#### Scenario: No text answers for the whole system

- GIVEN every state of the page
- WHEN every text is read
- THEN none says that nothing is open on any exchange, and none says that the mode can be changed

#### Scenario: An element with a strategy id on no tab is shown on its strategy's page

- GIVEN a position with a strategy id whose exchange is no tab
- WHEN the strategy's detail page renders
- THEN the position is in its section, and no Strategies tab shows it

#### Scenario: An element with no strategy id on no tab is drawn nowhere

- GIVEN a position with a null strategy id whose exchange is no tab
- WHEN every page is rendered
- THEN no page draws it and no line says that it exists

### Requirement: The Strategy Detail Page Lists Its Open Positions Above The Closed Trades

> **Added 2026-10-12 (owner decision 65, the second and third questions; design addendum "open positions" § H, "The detail section"; prototype examples 13 to 17 and 19 to 21).**

The strategy detail page MUST carry a section headed "Open positions", full
width, between the two-column grid and the closed trades. It MUST show every
position of the strategy, dry-run ones included, selected by the strategy's id
over the WHOLE answer: a strategy's page shows its positions wherever the
ledger put them, and the tabs follow the strategy's exchange. It MUST NOT wait
for the exchange scope. From `md` the positions MUST be a table with these
columns, and no other:

| Column | What the cell holds |
| --- | --- |
| Opened (UTC) | the date and, under it in the faint ink, the time |
| Pair | the market keys; under them the origin's word in its token |
| Side | `LONG` or `SHORT` |
| Size | the size, with its base currency as a unit; under it "of {opened} opened" when `opened_size` differs from `size` |
| Entry | the entry price; under it "average of N fills" when `fill_count` is above one |
| Fees {currency} | the fees, and each fee in another currency beside them, as the closed trades table writes them |
| Margin granted {currency} | the margin the share took from the pool, not what the exchange holds now |
| Leverage | the leverage with an `x`, as recorded (`2.00000000` is read `2x`) |

The table MUST have NO notional column: the notional is nearly margin times
leverage, and the exact figure is the size times the entry price, both on the
row. The leverage MUST be left empty where none was recorded and MUST NEVER be
filled in or read as `1x`. A rehearsal position MUST show `1x` because 1 was
recorded. The column words are those of the closed trades table ("Opened (UTC)",
"Pair", "Side", "Size", "Entry", "Fees {currency}"), reused.

#### Scenario: A live position with every column

- GIVEN strategy S1 holds a live `AAVEUSDT` LONG of 0.82 AAVE at 184.3 with fees 0.17 USDT, margin 121.80 USDT and leverage `2.00000000`
- WHEN S1's detail page renders
- THEN a section "Open positions" appears above "Closed trades" with one row whose cells read the date and time of opening, `AAVEUSDT` with "Live" under it, `LONG`, `0.82` with the unit AAVE, `184.3`, `0.17`, `121.80` and `2x`, and the heading of the Margin column reads "Margin granted USDT"

#### Scenario: No notional column

- GIVEN any open position
- WHEN the table renders
- THEN its column headings are exactly Opened (UTC), Pair, Side, Size, Entry, Fees, Margin granted and Leverage

#### Scenario: A rehearsal position reads 1x

- GIVEN a rehearsal position whose recorded leverage is `1.00000000`
- WHEN it renders
- THEN its Leverage cell reads `1x`

#### Scenario: A position with no recorded leverage is not read as 1x

- GIVEN a position whose leverage is null
- WHEN it renders
- THEN its Leverage cell is a dash, with "not recorded" for a screen reader, and not `1x`

#### Scenario: A position closed in part shows what was opened

- GIVEN `size` `0.3` and `opened_size` `0.5` on AAVE
- WHEN it renders
- THEN the Size cell reads `0.3` with "of 0.5 opened" under it

#### Scenario: A position opened by three fills says so

- GIVEN `fill_count` 3
- WHEN it renders
- THEN "average of 3 fills" appears under the entry price, and for `fill_count` 1 it does not

#### Scenario: A fee in another currency sits beside the fees

- GIVEN `other_fees` holds `0.001 SOL`
- WHEN the row renders
- THEN the Fees cell shows the fees and "+ 0.001 SOL" beside them

#### Scenario: The section selects by strategy id over the whole answer

- GIVEN S1 has a position whose pool names another exchange than S1's
- WHEN S1's detail page renders
- THEN the position is in the section

#### Scenario: Dry-run and live positions are listed together

- GIVEN S1 holds a rehearsal position and a live one
- WHEN the page renders
- THEN both are rows, each with its origin's word under the pair

#### Scenario: An empty section

- GIVEN S1 holds nothing and the read succeeded
- WHEN the page renders
- THEN the section reads "No open position." under its heading

#### Scenario: Loading, a failed first read and a failed refresh

- GIVEN the answer is loading, then the first read failed, then a refresh fails after a good read
- WHEN the section renders in each state
- THEN it reads "Reading open positions…", then the error sentence with "Read again", then the last answer with "Could not be refreshed since {time} UTC."

### Requirement: An Absent Figure Of An Open Position Is A Dash With Its Reason

> **Added 2026-10-12 (owner decision 65, "left empty ... never filled in"; design addendum "open positions" § D and § H, "A null is a dash with its reason"; prototype examples 15 and 17).**

Wherever a value of an open position is null (in the detail table, in its cards
and in the Overview's list) the cell MUST be a dash, with its reason in text for
a screen reader, and the panel MUST NOT pass a null on to a formatter. The
reason MUST be "figures not readable" for the side, the size and the entry of
any position whose figures are missing, and for EVERY empty cell of a position
the facts could not decorate (Opened, Side, Size, Entry, Fees, Margin granted
and Leverage). "not recorded" MUST be kept for the one case it is true of: a
position that has its facts and no leverage. A position whose figures are
missing MUST show, in a sub-row directly under it, the reason in sans type in the
secondary ink, one of:

| `figures_missing` | Text |
| --- | --- |
| `UNRESOLVED_SYMBOL` | The pair's base currency cannot be told from the pool's currency, so the side and the size are not derived. |
| `SEVERAL_MARKETS` | The fills of this position name more than one pair. |
| `FLIPPED` | The fills sold more than was bought, or bought more than was sold. The entry price is not derived. |
| any other | The figures could not be derived from the fills. |

#### Scenario: An unresolved symbol

- GIVEN a position with `figures_missing` `UNRESOLVED_SYMBOL`, fees, margin and leverage present
- WHEN it renders
- THEN the Side, Size and Entry cells are dashes with "figures not readable", a sub-row under the row gives the first reason above, and the fees, margin and leverage are shown

#### Scenario: Each other reason has its text

- GIVEN positions with `SEVERAL_MARKETS`, `FLIPPED` and `INCONSISTENT`
- WHEN they render
- THEN each sub-row reads the matching text above, and `INCONSISTENT` reads "The figures could not be derived from the fills."

#### Scenario: A position the facts could not decorate has seven dashes in the detail table

- GIVEN a position with `figures_missing` `NO_FACTS`
- WHEN it renders in a table that has the Opened and Fees columns
- THEN every empty cell is a dash whose reason is "figures not readable", and none reads "not recorded"

#### Scenario: A null leverage on a position with facts

- GIVEN a position with facts and a null leverage
- WHEN it renders
- THEN the Leverage cell is a dash read as "not recorded"

#### Scenario: The Opened cell of a null is a dash

- GIVEN `opened_at` is null
- WHEN the row renders
- THEN the Opened cell is a dash, not a date

### Requirement: An Order In Flight Is A Dashed Line Under The Open Positions

> **Added 2026-10-12 (owner decision 65; design addendum "open positions" § H, "One component for the two lines"; prototype example 19).**

The detail page MUST show each order in flight of the strategy as a line in a
list under the positions table, or under "No open position." when the strategy
holds no position. The line MUST run the width of its container, wrap, have a
DASHED border in the origin's colour as on a chip, a transparent fill and mono
type, and MUST read, separated by ` · `: the pair; "order in flight"; "opening"
or "closing" (left out when the action is null); the origin's word in its token;
and "sent {time} UTC" (left out when the instant is null), the time in hours and
minutes. The order of the Overview is not drawn there (see "The Overview Lists
Every Open Position Of The Selected Exchange, Pool By Pool").

#### Scenario: A closing dry-run order under a position

- GIVEN S1 holds a position and a closing order sent at 21:12 on `SFPUSDT`, origin dry run
- WHEN the detail page renders
- THEN under the table is a dashed line reading `SFPUSDT · order in flight · closing · Dry run · sent 21:12 UTC`

#### Scenario: An order with nothing else

- GIVEN S1 holds no position and one opening live order
- WHEN the page renders
- THEN "No open position." is drawn and the dashed line follows it

#### Scenario: An undecorated order leaves its two parts out

- GIVEN an order whose `action` and `submitted_at` are null
- WHEN its line renders
- THEN it reads the pair, "order in flight" and the origin, with no "opening", "closing" or "sent"

#### Scenario: An order sent on an earlier day carries its date

- GIVEN an order sent yesterday at 21:12 UTC and an answer read today
- WHEN its line renders
- THEN the sent time is written with its date before it

### Requirement: On The Detail Page And The Overview The Venue Mark Is One Solid Red Line Under Its Row

> **Added 2026-10-12 (owner decision 65, bullets of 2026-10-12, the second review and the third; design addendum "open positions" § E and § H, "One component for the two lines"; prototype examples 18, 24 and 25e).**

On the detail page and in the Overview's list, a position that carries a
`venue_disagreement` MUST be followed by ONE line directly under its row, across
the table's width, in the same type and spacing as the line of an order in
flight, with a SOLID red border. Its parts, separated by ` · `, MUST be: the
pair; "venue disagrees" in red; "exchange {x}, ledger {y}" with the two nets as
stored, each followed by the position's base currency when it has one (`exchange
0 AAVE, ledger 0.82 AAVE`); "last compared {time} UTC", the time with seconds;
"shared by N positions on this pair", ONLY when N is above one; and then the
words of the discrepancy's state and the link "See the discrepancy", under the
same rule as the chip (revised 2026-10-16, owner decision 66: "being booked
automatically", or the words of the reason, and no claim while the
confirmed-discrepancies query loads or failed or when the id is in neither of
its lists; previously the link "See the pending decision" or the words "no
booking is proposed", from the proposals). The line
MUST be a group named "Venue disagrees, {pair}" and its link MUST be named "See
the discrepancy, {pair}". In a card it MUST be the card's last element.
Sub-rows under a position MUST come in this order: the venue line; the reason
the figures are missing; the reservation's note, "Its reservation reads
{status}, not FILLED.", when its status is not `FILLED`.

#### Scenario: The line with a link

- GIVEN `AAVEUSDT` carries a disagreement with venue net 0 and ledger net 0.82, compared at 21:38:12, whose id is in `being_booked`
- WHEN the detail page renders
- THEN under its row is one solid red line reading `AAVEUSDT · venue disagrees · exchange 0 AAVE, ledger 0.82 AAVE · last compared 21:38:12 UTC · being booked automatically · See the discrepancy`

#### Scenario: The line without a claim

- GIVEN the same disagreement and the confirmed-discrepancies query loading, failed, or the id in neither list
- WHEN the line renders
- THEN it ends after the nets and the time, with no words about booking and no link

#### Scenario: A shared disagreement says so

- GIVEN two positions on `AAVEUSDT` and `allocation_count` 2
- WHEN each line renders
- THEN each includes "shared by 2 positions on this pair" before the link or the words, and for `allocation_count` 1 the part is not drawn

#### Scenario: The line is one component with the order line

- GIVEN a position's venue line and an order's line on the same page
- WHEN they render
- THEN they have the same width, type and spacing, the first with a solid red border and the second with a dashed one

#### Scenario: The sub-rows are in order

- GIVEN a position with a venue disagreement, `UNRESOLVED_SYMBOL` and a reservation that reads `EXPIRED`
- WHEN it renders
- THEN under the row come the venue line, the reason, and "Its reservation reads EXPIRED, not FILLED."

#### Scenario: A position that is FILLED has no reservation note

- GIVEN a position whose reservation reads `FILLED`
- WHEN it renders
- THEN no reservation note is drawn

#### Scenario: The line has its accessible names

- GIVEN a venue line with a link
- WHEN it is read by assistive technology
- THEN it is a group named "Venue disagrees, AAVEUSDT" and the link is named "See the discrepancy, AAVEUSDT"

#### Scenario: In a card the line is last

- GIVEN a narrow viewport and a position with a disagreement
- WHEN its card renders
- THEN the venue line is the card's last element

### Requirement: The Notes And The Unmatched Sentence Of The Section Are Drawn Only When True

> **Added 2026-10-12 (owner decision 65; design addendum "open positions" § H, "The detail section" and § I; prototype examples 15, 17, 19a and 26b).**

Under the detail section's table and its order lines, a note MUST be drawn only
when a row on screen makes it true, in this order: the dry-run note, the note of
a position of both origins, and the margin note.

- Dry run, for at least one position of origin `rehearsal`: "A dry-run position
  was filled by the simulated exchange, at 1x. It is not at the exchange and
  enters no total."
- Both origins, for at least one position of origin `mixed`: "This position
  holds dry-run and live fills. Neither mode can close it safely: check it
  against the exchange by hand."
- Margin, for at least one position: "Margin granted is what the share took
  from the pool when the position opened. It is not what the exchange holds
  now."

While the strategy's OWN EXCHANGE holds an element with no strategy id, the
section MUST say "{N} open position(s) could not be matched to a strategy. The
Strategies page names it/them." (singular for one, plural for more, counting
positions and orders together): in place of "No open position." when the
strategy has no position of its own, and above the notes otherwise. "No open
position." MUST NEVER be drawn while such an element exists. An unmatched element
of another exchange MUST NOT count. The Overview's list MUST draw no notes.

#### Scenario: Only the true notes are drawn

- GIVEN S1 holds one live position
- WHEN the section renders
- THEN only the margin note is drawn

#### Scenario: A rehearsal position draws the dry-run note and the margin note

- GIVEN S1 holds one rehearsal position
- WHEN the section renders
- THEN the dry-run note is drawn, then the margin note

#### Scenario: A position of both origins draws its note

- GIVEN S1 holds a position with origin `mixed`
- WHEN the section renders
- THEN the dry-run note is not drawn, the note of both origins is drawn, then the margin note

#### Scenario: The notes' order

- GIVEN S1 holds a rehearsal position and a `mixed` one
- WHEN the section renders
- THEN the notes read dry-run, both origins, margin, in that order

#### Scenario: No position, no note

- GIVEN S1 holds nothing
- WHEN the section renders
- THEN no note is drawn

#### Scenario: An unmatched position replaces "No open position."

- GIVEN S1 holds no position and S1's exchange holds one position with no strategy id
- WHEN the page renders
- THEN the section reads "1 open position or order could not be matched to a strategy. The Strategies page names it." and not "No open position."

#### Scenario: One unmatched order and no position is not called a position

- GIVEN S1 holds no position and S1's exchange holds one order in flight with no strategy id and no position with none
- WHEN the section renders
- THEN it reads "1 open position or order could not be matched to a strategy. The Strategies page names it." and not "No open position."
- AND in Spanish it reads "1 posición u orden abierta no se pudo asociar a una estrategia. La página Estrategias la nombra."

#### Scenario: Several unmatched elements

- GIVEN S1's exchange holds two unmatched positions and S1 holds one position
- WHEN the section renders
- THEN above the notes it reads "2 open positions or orders could not be matched to a strategy. The Strategies page names them."

#### Scenario: An unmatched element of another exchange is not counted

- GIVEN the only unmatched position is on another exchange than S1's
- WHEN S1's section renders with no position
- THEN it reads "No open position."

### Requirement: On A Phone Open Positions Are Cards

> **Added 2026-10-12 (owner decision 65; design addendum "open positions" § H; prototype examples 20 and 24).**

Below `md` each open position MUST be a card in place of a table row: an
`article` named by its pair and side (`AAVEUSDT LONG`), the pair and the side in
the card's head with the origin's word at its right, then the same labelled
values in two columns, each null a dash with its reason. The card's sub-rows MUST
be its last elements, in the order of "On The Detail Page And The Overview The
Venue Mark Is One Solid Red Line Under Its Row". On the Overview the strategy's
name MUST be under the card's head.

#### Scenario: Three positions at desktop and phone width

- GIVEN S1 holds three positions
- WHEN the section renders at desktop width and at 390 px
- THEN it is a table at the first and three cards at the second

#### Scenario: A card is named by its pair and side

- GIVEN a card for `AAVEUSDT` LONG
- WHEN it is read by assistive technology
- THEN it is an `article` named "AAVEUSDT LONG"

#### Scenario: A card carries the same values

- GIVEN a position at phone width
- WHEN its card renders
- THEN it shows the opened date, size, entry, fees, margin granted and leverage, with the origin's word at the right of its head

### Requirement: The Overview Lists Every Open Position Of The Selected Exchange, Pool By Pool

> **Added 2026-10-12 (owner decision 65, 2026-10-12: "Lo de Overview me parece bien, lo incorporamos"; design addendum "open positions" § H, "The Overview part"; prototype examples 22 to 24).**

Under the month grid and its summary, each pool panel of the Overview MUST list
the open positions whose pool has exactly that pool's three values (exchange,
venue and settlement currency), never the exchange alone, so that two pools
never mix (rule 7). The list MUST be the detail table's: the heading "Open
positions" and the columns Strategy, Opened (UTC), Pair, Side, Size, Entry,
Margin granted {currency} and Leverage, with NO Fees column and no notional
column. The Strategy cell MUST be a link to the strategy's page, or plain text
when the position has no strategy id (its six empty cells are then dashes). Rows
MUST follow the route's order. A position the venue disagrees on carries its
line under the row, or in the card. The list MUST be drawn even when the pool has
no performance report, since a pool without a report can hold a position, and it
MUST draw the detail section's three states with its texts: "Reading open
positions…", the error sentence with "Read again", and "No open position.", with
the heading always drawn. The list MUST draw no notes.

> **Decided by the owner on 2026-10-13 (Q8): no.** Orders in flight are NOT drawn
> on the Overview; a pool whose only open thing is an order reads "No open
> position.". They stay on the Strategies page and on the strategy's page.

#### Scenario: Three positions of two strategies in one pool

- GIVEN pool `(bybit, usdt-m, USDT)` holds three positions of two strategies
- WHEN the Overview renders for Bybit
- THEN under the month grid and its summary is the list "Open positions" with three rows, each with its strategy's name as a link in the first column

#### Scenario: No Fees column

- GIVEN the Overview's list
- WHEN its headings are read
- THEN they are Strategy, Opened (UTC), Pair, Side, Size, Entry, Margin granted USDT and Leverage

#### Scenario: Two pools of one exchange never mix

- GIVEN Bybit has pools `(bybit, usdt-m, USDT)` and `(bybit, coin-m, BTC)` each holding a position
- WHEN the Overview renders
- THEN each position is listed only in its own pool's panel

#### Scenario: A pool without a report still lists its position

- GIVEN a pool whose performance report is missing and which holds a position
- WHEN the Overview renders
- THEN the list's row is drawn

#### Scenario: A position with no strategy id is plain text

- GIVEN a position with a null strategy id in a pool of the selected exchange
- WHEN the list renders
- THEN its strategy's name is plain text, not a link, and the six empty cells are dashes

#### Scenario: A position the venue disagrees on carries its line

- GIVEN a position with a disagreement
- WHEN the list renders, as a table and as a card
- THEN the venue line is under its row or inside its card

#### Scenario: The list's states

- GIVEN the read is loading, then failed, then empty
- WHEN the pool panel renders in each state
- THEN under the heading it reads "Reading open positions…", then the error sentence with "Read again", then "No open position."

#### Scenario: A failed read is not read as zero

- GIVEN the read failed
- WHEN the pool panel renders
- THEN no count is drawn and the error sentence is right under the heading

#### Scenario: No notes under the list

- GIVEN a list holding a rehearsal position
- WHEN it renders
- THEN no dry-run, both-origins or margin note is drawn under it

#### Scenario: An order in flight is not drawn on the Overview

- GIVEN a pool whose only open thing is an order in flight
- WHEN the Overview renders
- THEN the list reads "No open position." and no order line is drawn

#### Scenario: The strategy's name is under the card's head on a phone

- GIVEN a phone viewport
- WHEN the list renders
- THEN each card has the strategy's name under its head

#### Scenario: Nothing sits between the chart and the grid on a phone

- GIVEN a phone viewport
- WHEN the Overview renders
- THEN nothing is between the chart and the month grid (the rail is gone, owner decision 66), and the positions are cards under the grid

### Requirement: The Overview's Count Says How Many Are Open And How Many Of Them Are Dry Run

> **Added 2026-10-12 (owner decision 65, 2026-10-11 and 2026-10-12; design addendum "open positions" § H, "The Overview's count" and § I; prototype example 23).**

The Overview's monthly summary MUST count the pool's open positions, replacing
the live-only sentence "N open trades not in the curve" ON THE OVERVIEW. The
count MUST sit where the live-only part sat, after the worst month. It MUST
write nothing when no position is open; "N open" when none of them is a dry run;
and "N open, M of them dry run" otherwise. M counts the positions whose origin
is `rehearsal`; a position of both origins MUST be in N and not in M, and its
row says what it is. While the answer is loading or its read failed, the summary
MUST write no part about open positions, old or new, and the list's error
sentence stays right under it. The summary is drawn only when the pool has a
report, so a pool that holds a position and has no report MUST show its list and
no count. The API's `excluded.open_trade_count` MUST stay, as what the curve
leaves out.

#### Scenario: Three open, one of them dry run

- GIVEN a pool with three open positions, one of origin `rehearsal`
- WHEN the summary renders
- THEN it reads "3 open, 1 of them dry run"

#### Scenario: Two open and none dry run

- GIVEN a pool with two live positions
- WHEN the summary renders
- THEN it reads "2 open"

#### Scenario: One open and live

- GIVEN a pool with one live position
- WHEN the summary renders
- THEN it reads "1 open"

#### Scenario: One open, a dry run, reads in the singular

- GIVEN a pool with one position of origin `rehearsal`
- WHEN the summary renders
- THEN it reads "1 open, dry run", and in Spanish "1 abierta, en simulación" (corrected after the final review, 2026-10-13, with the owner's agreement)

#### Scenario: Two or more open, some of them a dry run, read as approved

- GIVEN a pool with two positions, one of them of origin `rehearsal`, or with three that are all of origin `rehearsal`
- WHEN the summary renders
- THEN it reads "2 open, 1 of them dry run" or "3 open, 3 of them dry run", and in Spanish "2 abiertas, 1 de ellas en simulación" or "3 abiertas, 3 de ellas en simulación"

#### Scenario: Nothing open writes nothing

- GIVEN a pool with no open position
- WHEN the summary renders
- THEN it has no part about open positions

#### Scenario: A position of both origins is in N and not in M

- GIVEN a pool with one `mixed` position and one live one
- WHEN the summary renders
- THEN it reads "2 open"

#### Scenario: A rehearsal position counts although the curve leaves it out

- GIVEN a pool whose report's `open_trade_count` is 0 and which holds a rehearsal position
- WHEN the Overview renders
- THEN the summary reads "1 open, dry run"

#### Scenario: No part while loading or after a failed read

- GIVEN the positions answer is loading, and then its read failed
- WHEN the summary renders
- THEN it has no part about open positions in either state

#### Scenario: A pool with no report has a list and no count

- GIVEN a pool that holds a position and whose report is missing
- WHEN the Overview renders
- THEN the list shows the row and no count is drawn

#### Scenario: Spanish

- GIVEN the locale is Spanish and three open positions, one of them dry run
- WHEN the summary renders
- THEN it reads "3 abiertas, 1 de ellas en simulación", and for a single live position "1 abierta"

### Requirement: The Detail Page's Own Count Of Open Trades Is Left As It Is

> **Added 2026-10-12 (design addendum "open positions" § H, "The Overview's count", P27 and § O, Q6).**

The same summary component is drawn on the strategy detail page's performance
block, where it writes "N open trades not in the curve" for ONE strategy, live
positions only. Decision 65 names the Overview's count and says nothing of this
one, which nobody had seen. The detail page's sentence MUST NOT change.

> **Decided by the owner on 2026-10-13 (Q6): it stays as it is.** The sentence
> keeps counting live positions only and does not take the Overview's new form.
> The section "Open positions" sits a little below it and lists every position,
> dry run included, so the two can read differently ("1 open trade not in the
> curve" beside two rows, one of them a dry run); both statements are true as
> worded.

#### Scenario: The detail page keeps its sentence

- GIVEN the strategy's report says one open trade is not in the curve and the strategy holds a live and a rehearsal position
- WHEN the detail page renders
- THEN the performance block reads "1 open trade not in the curve" and the section "Open positions" lists both positions

#### Scenario: The Overview does not write it

- GIVEN the same report on the Overview's pool panel
- WHEN the summary renders
- THEN the live-only sentence is not drawn and the new count is

### Requirement: The Top Bar's Live Badge Is Drawn In The Gain Colour

> **Added 2026-10-12 (owner decision 65, bullets of 2026-10-12; design addendum "open positions" § H, "The Live badge").**

The top bar's mode badge, when the API reports `dry_run: false`, MUST read
"Live" in the `gain` colour (a `gain` border and `gain` text), the colour the
marks give the origin "Live". The badge states the mode and is not an alarm. The
badge MUST still be always visible (owner decision 32). It MUST still read "Dry
run" in amber when the API reports `dry_run: true`. The neutral states MUST stay
neutral: while the mode is not read, or its read failed, the badge MUST show
neither mode and MUST NOT use `gain`, amber or the loss colour. Its Spanish
texts, "En vivo" and "Modo simulación", MUST not change.

(Previously: the "Live" badge was drawn in the loss colour, an implementation
choice and not an owner decision.)

#### Scenario: Live is cyan

- GIVEN `/health` reports `dry_run: false`
- WHEN the top bar renders
- THEN the badge reads "Live" with a `gain` border and `gain` text, and no loss colour

#### Scenario: Dry run stays amber

- GIVEN `/health` reports `dry_run: true`
- WHEN the top bar renders
- THEN the badge reads "Dry run" in the amber token

#### Scenario: A pending or failed read stays neutral

- GIVEN the mode has not been read, and in a second case its read failed
- WHEN the top bar renders
- THEN the badge shows neither "Live" nor "Dry run" and uses a neutral colour

#### Scenario: The badge and the marks agree

- GIVEN `dry_run: false` and a live position's mark
- WHEN both render
- THEN the badge and the word "Live" of the mark use the same colour

#### Scenario: Spanish

- GIVEN the locale is Spanish
- WHEN the badge renders in each mode
- THEN it reads "En vivo" and "Modo simulación"

### Requirement: Times And Figures Of Open Positions Are Written One Way

> **Added 2026-10-12 (design addendum "open positions" § H, "Times" and "Figures"; § J, the place where what is built departs from the picture, decided by the owner on 2026-10-13, Q9).**

Every time MUST have "UTC" written after it. "Last read", "could not be
refreshed since" and "last compared" MUST be written as hours, minutes and
seconds; "sent" as hours and minutes; "Opened" as the date and the time on two
lines. A clock time that is not on the UTC day of the answer's `as_of` MUST be
written with its date before it, so that an order sent yesterday at 21:12 does
not read as sent minutes ago and a venue mark frozen since the mode was changed
does not read as compared today. Prices and sizes MUST be written as the closed
trades table writes them, the two nets as plain figures, and fees and margin with
the currency's decimals (`121.80`), so that one page writes a figure one way.
The leverage MUST be written without its stored zeros and followed by `x`
(`2.00000000` reads `2x`).

> **Decided by the owner on 2026-10-13 (Q9): `184.3`.** In Spanish a price and a
> size MUST read with a decimal POINT (`184.3`, `0.82 AAVE`), as the closed
> trades table beside them does today, where the approved prototype's example 25
> draws a comma (`184,3`, `0,82 AAVE`). A money amount keeps the language's
> separator (`0,17`) and a margin reads `121.80`, with the currency's two
> decimals, where some of the prototype's samples read `121.8`.

#### Scenario: Three kinds of time

- GIVEN `as_of` 21:40:03 UTC, an order sent at 21:12 and a position opened on 2026-10-11 at 21:12
- WHEN they render
- THEN "Last read" reads `21:40:03 UTC`, the order reads `sent 21:12 UTC`, and the Opened cell shows the date and the time on two lines

#### Scenario: A time of another day carries its date

- GIVEN a venue mark last compared yesterday at 21:12:00 UTC and an answer read today
- WHEN the venue line renders
- THEN "last compared" is written with yesterday's date before the time

#### Scenario: A time of the same day has no date

- GIVEN a venue mark last compared today at 21:12:00 UTC
- WHEN the line renders
- THEN "last compared" reads the time only

#### Scenario: A margin keeps the currency's decimals

- GIVEN a margin granted of `121.8` USDT
- WHEN the row renders
- THEN it reads `121.80`

#### Scenario: Spanish prices follow the table under them

- GIVEN the locale is Spanish and a position with entry price 184.3 and size 0.82 AAVE
- WHEN the section renders
- THEN the entry reads `184.3` and the size `0.82`, with a point, as the closed trades table writes them

### Requirement: Open Positions Show No Result, No Current Price And No Notional

> **Added 2026-10-12 (owner decision 65, scope B; design addendum "open positions" § N).**

The open-position views MUST NOT show an unrealised PnL, a current price, a
return or any figure read from the venue. This change MUST add no new read of
any venue and no periodic remote read. They MUST NOT show a notional column. They
MUST NOT show the confirmed discrepancies themselves: the venue mark states the
disagreement and what is happening to it, and leads only to its item in the
Discrepancies view (revised 2026-10-16, owner decision 66; previously "and
whether a booking is proposed, and leads nowhere else", the view being then
left for later). An open position MUST NOT open onto its fills: a row is a row, not a
control, and no dialog opens from it. The Strategies page MUST show nothing about
another exchange. No open position MUST enter any total, and the panel MUST show
no figure that adds the money of two pools. No mark MUST say a result.

#### Scenario: No price or PnL on any open position

- GIVEN open positions in every view
- WHEN their text is read
- THEN none shows a unrealised PnL, a current price, a mark price or a return

#### Scenario: No request to a venue

- GIVEN the open-position views are rendered
- WHEN the network is read
- THEN the only request for them is `GET /api/positions/open`

#### Scenario: A row does not open a dialog

- GIVEN an open position's row
- WHEN the owner clicks it
- THEN no dialog opens and no fills are shown

#### Scenario: The venue mark leads only to its item in the Discrepancies view

- GIVEN a venue mark whose id is in `being_booked`
- WHEN the link is read
- THEN it leads to `/discrepancies` with the hash `#discrepancy-<id>` and to no other place

#### Scenario: No blended total

- GIVEN positions in two pools of different currencies
- WHEN the Overview renders
- THEN each pool's count and list stand alone and no figure adds the two

### Requirement: Every Open-Positions Text Exists In English And Spanish

> **Added 2026-10-12 (owner decision 65; design addendum "open positions" § I, approved with the prototype).**

Every text of the open-position views MUST exist in `en.json` and `es.json` and
be resolved through i18n, with no hardcoded display text. The English MUST be the
approved text of design § I, letter for letter, and so MUST the Spanish for every
text that example 25 of the prototype draws: "Abiertas", "Órdenes en curso",
"Última lectura", "Fuera de esta lista: {{items}}.", "archivada", "cifras no
legibles", "Leer de nuevo", "Simulación", "En vivo", "orden en curso", "El
exchange no coincide", "No hay un registro propuesto para esta diferencia.",
"Ver la decisión pendiente", "Posiciones abiertas", "Margen otorgado
{{currency}}" and "Apalancamiento". The Spanish of the texts the prototype does
not draw is design § I's. The texts are keyed in the groups `positions.state.*`,
`positions.marks.*`, `positions.origin.*`, `positions.order.*`,
`positions.venue.*`, `positions.table.*`, `positions.reason.*`,
`positions.note.*` and `positions.sideUnreadable`, and, for the Overview,
`overview.open.strategy`, `overview.monthlySummary.openAll_*` and
`overview.monthlySummary.openWithRehearsal`. The column headings, the sides
(`LONG`, `SHORT`) and the fee in another currency MUST be the existing
`strategies.performance.trades.*` keys, reused unchanged. The key
`overview.monthlySummary.open_*` MUST remain, because the detail page still
writes it. The punctuation between parts (the colon after a label, ` · `, `; `)
is written by the component and is the same in both languages. A text with a
count MUST have both its singular and plural forms in both files. The two files
MUST hold the same set of keys. No text MUST say that nothing is open anywhere
or permit changing the mode.

#### Scenario: Every view reads in Spanish

- GIVEN the locale is Spanish and the Strategies page, a detail page and the Overview show open positions, an order in flight and a venue mark
- WHEN every visible string is read
- THEN each is Spanish, sourced from i18n, `LONG` and `SHORT` are unchanged, and no English text of this change remains

#### Scenario: The Spanish of example 25 is exact

- GIVEN the locale is Spanish and the states of examples 25a to 25e
- WHEN the texts are read
- THEN they equal design § I's Spanish column letter for letter, including "Fuera de esta lista" and "El exchange no coincide"

#### Scenario: The figures in Spanish

- GIVEN the locale is Spanish
- WHEN the figures render
- THEN they read `Abiertas: 2 · Órdenes en curso: 1 · Última lectura: 21:40:03 UTC`

#### Scenario: The English is the approved text

- GIVEN the locale is English
- WHEN the failure, stale and loading texts render
- THEN they read exactly "Open positions could not be read. A row without a mark does not mean that nothing is open.", "Could not be refreshed since 21:38:12 UTC." and "Reading open positions…"

#### Scenario: Every new key is in both files

- GIVEN the two locale files
- WHEN their open-position keys are compared
- THEN the sets are equal, and each key with a count has its singular and plural forms in both

#### Scenario: Reused keys are unchanged

- GIVEN the locale files before and after the change
- WHEN `strategies.performance.trades.*` and `overview.monthlySummary.open_*` are compared
- THEN they are equal

### Requirement: The Open-Positions Views Are Named For Assistive Technology

> **Added 2026-10-12 (design addendum "open positions" § H, "Accessibility").**

Each mark MUST be text, not colour or shape alone: the origin is a word, and so
are "order in flight" and "venue disagrees". A row's list of marks MUST be named
"Open positions of {name}". The dashes MUST carry their reason in text for a
screen reader, as the closed trades table does. The venue line is a group and
its link a real link, each named with the pair. The loading text is a status and
the first failure an alert; the figures' live region MUST hold the counts and the
lines under them and not the time. The "Read again" button MUST be 44 px tall.

#### Scenario: A row's marks have a name

- GIVEN strategy "STX 4h" holds a position
- WHEN its row is read by assistive technology
- THEN its list of marks is named "Open positions of STX 4h"

#### Scenario: The origin is a word

- GIVEN a dry-run mark, a live mark and a mark of unknown origin
- WHEN their text is read with colour ignored
- THEN each says "Dry run", "Live" or "origin unknown"

#### Scenario: A dash has its reason

- GIVEN a position with a null leverage
- WHEN its cell is read by a screen reader
- THEN it reads "not recorded"

#### Scenario: Status and alert roles

- GIVEN the loading state and the first failure
- WHEN their roles are read
- THEN the loading text has `role="status"` and the error sentence `role="alert"`

### Requirement: The Closed Trades Table Shows Each Operation's Figures

> **Added 2026-10-04 (owner decisions 43 and 44).**

The strategy detail view MUST show a section titled "Closed trades" /
"Operaciones cerradas", full width below the page's two-column area and above
the delete control, with one row per closed operation of the strategy, each in
the strategy's own pool and in that pool's native settlement currency (for
example USDT for `(bybit, usdt-m, USDT)`). Every cell MUST show the number the server served, and the panel MUST NOT compute any money figure from them. A missing
figure MUST NEVER be shown as zero. In the table, Entry, Exit and Size are written with at most five decimals and no trailing zeros, or with four significant digits when five decimals would leave fewer (so a small price never reads 0), and Fees like the PnL beside them, with the pool currency's decimals and no sign; the detail dialog keeps up to eight significant digits (owner decision 46, 2026-10-05).

The columns, in this order on a wide screen, are: Opened (UTC), Closed (UTC),
Pair (with the rehearsal tag when it applies), Side, Entry, Exit, Size, Fees
{currency}, PnL {currency}, PnL %, Pool at open (heading shortened, owner decision 46, 2026-10-05), and a Details control.
They MUST be shown by viewport width:

- at every width: Closed, Pair, Side, PnL, PnL %, Details (six columns);
- from 768 px: also Entry and Exit (eight columns);
- from 1280 px: also Size, Fees and Pool at open (eleven columns);
- from 1440 px: also Opened (all twelve).

Below about 560 px the table MUST scroll sideways inside its own wrapper rather
than overflow the page. Every figure a narrower width hides MUST be in the
detail dialog. The column formerly headed "Return" MUST read "PnL %" in both
languages, and it is the return on the pool's capital at open, not on the
position's margin. The side of an operation MUST read "LONG" or "SHORT" in both
English and Spanish.

A null Entry, Exit or Size MUST show the existing em dash with a reason for a
screen reader ("This figure cannot be derived from the operation's fills." /
"Esta cifra no se puede derivar de las ejecuciones de la operación."). A fee in
another currency MUST show after the fees as "+ 0.00012 BNB". An operation whose
fees are incomplete shows an asterisk right after its PnL figure, explained by one note below the table and its paging controls, after the dry-run sentences, that appears only when a row of the page on screen has incomplete fees (owner decision 46, 2026-10-05); the words stay in the detail dialog. A figure served as
a string that is not a number MUST read as "unreadable", as the PnL cell does
today. An operation with no recorded pool capital MUST show PnL % and Pool
at open empty, never an invented number. A strategy with no closed
operation MUST show the existing defined empty state.

The panel MUST send `include_rehearsal=true` on every request of this table,
the first page and every later one.

#### Scenario: A wide screen shows every column

- GIVEN a viewport of 1440 px and a strategy on pool `(bybit, usdt-m, USDT)` with a closed LONG
- WHEN the section renders
- THEN twelve columns are shown in the order Opened, Closed, Pair, Side, Entry, Exit, Size, Fees USDT, PnL USDT, PnL %, Pool at open, Details

#### Scenario: A narrow screen keeps six columns

- GIVEN a viewport of 600 px
- WHEN the section renders
- THEN exactly Closed, Pair, Side, PnL USDT, PnL %, and Details are shown

#### Scenario: Each width tier adds its columns

- GIVEN viewports of 768 px, 1280 px and 1440 px
- WHEN the section renders at each
- THEN Entry and Exit appear from 768 px, Size, Fees and Pool at open from 1280 px, and Opened from 1440 px, and no column appears below its tier

#### Scenario: A row shows the stored figures

- GIVEN a closed LONG with entry price `"0.451200000000000000"`, exit price `"0.463100000000000000"`, size `"1250.000000000000000000"` and fees `"0.630000000000000000"`
- WHEN the row renders
- THEN it shows Entry 0.4512, Exit 0.4631, Size 1250, Fees 0.63, and PnL 14.245

#### Scenario: The side is LONG and SHORT in Spanish

- GIVEN the locale is Spanish and the list holds a LONG and a SHORT
- WHEN the section renders
- THEN the Side cells read "LONG" and "SHORT", not "Largo" or "Corto"

#### Scenario: The return column is PnL %

- GIVEN the locale is English, then Spanish
- WHEN the section renders
- THEN the column heading is "PnL %" in both

#### Scenario: A figure that cannot be derived shows an em dash, not zero

- GIVEN a row whose entry price, exit price and size are null
- WHEN the row renders
- THEN those three cells show an em dash with the reason for a screen reader, and no cell shows 0

#### Scenario: A fee in another currency follows the fees

- GIVEN a row whose other fees are `[{"currency": "BNB", "amount": "0.000120000000000000"}]`
- WHEN the row renders
- THEN its Fees cell shows the fees followed by "+ 0.00012 BNB"

#### Scenario: A row without pool capital shows PnL % empty

- GIVEN a row whose return and capital at open are null
- WHEN the row renders
- THEN PnL % and Pool at open are empty and PnL is shown

#### Scenario: Every request carries include_rehearsal

- GIVEN the section loads its first page and then its second page after a click on "Next"
- WHEN both requests are inspected
- THEN each carries `include_rehearsal=true`

### Requirement: Closed Trades Are Paged Twenty At A Time On A Click

> **Added 2026-10-04 (owner decision 44; behaviour approved by the owner's
> review of PR 12d and built in task 9p.8).**

The closed trades table MUST show ONE page of at most 20 operations at a time.
Pages MUST NEVER accumulate on screen: showing another page replaces the rows
of the current one. The table MUST request 20 operations at a time
(`limit=20`) and MUST page by keyset, with the cursor the server served (the
close instant and allocation id of the last row of the previous page), never by
an offset. Nothing MUST load on scroll; a page is requested only by a click.

Below the table the panel MUST show a "Previous" control, the number of the
page on screen, and a "Next" control. It MUST NOT show a total page count,
because the server serves none. The two controls are always present and are
disabled, never removed or hidden:

- "Previous" MUST be disabled on the first page. Elsewhere it MUST show the
  page before from the pages already loaded and MUST send no request.
- "Next" MUST be disabled when the current page's `next_cursor` is null and no
  later page is already loaded. Otherwise, when the next page has not been
  loaded yet, "Next" MUST request it with the cursor the current page served;
  when it is already loaded, "Next" MUST show it again with no request.
- While the next page is being requested, "Next" MUST be disabled.
- When the request for the next page fails, the current page MUST stay on
  screen, the panel MUST say that the next page could not be loaded, and "Next"
  MUST remain available to ask again.

Another strategy's list MUST start on its first page.

#### Scenario: The first request asks for 20

- GIVEN a strategy with 45 closed operations
- WHEN the section first loads
- THEN one request is made, with `limit=20` and no cursor, 20 rows are shown, the page number reads 1, "Previous" is disabled and "Next" is enabled

#### Scenario: A further page is requested only on a click

- GIVEN the first page was served with a `next_cursor`
- WHEN the owner scrolls to the bottom of the page without clicking
- THEN no further request is made

#### Scenario: Next requests the following page with the served cursor and replaces the rows

- GIVEN a strategy with 45 closed operations and page 1 on screen, served with a `next_cursor`
- WHEN the owner clicks "Next"
- THEN one request is made with `limit=20` and that cursor's `before_closed_at` and `before_allocation_id`, and no offset, page 2 shows its 20 rows and none of page 1's, the page number reads 2, and "Previous" is enabled

#### Scenario: The last page disables Next

- GIVEN the same strategy with page 3 on screen, which holds 5 rows and was served with `next_cursor` null
- WHEN the section renders
- THEN 5 rows are shown, the page number reads 3, "Next" is disabled and still present, and "Previous" is enabled

#### Scenario: Previous shows a loaded page with no request

- GIVEN pages 1 to 3 have been loaded and page 3 is on screen
- WHEN the owner clicks "Previous"
- THEN page 2's 20 rows are shown from the pages already loaded, the page number reads 2, and no request is made

#### Scenario: Next shows an already loaded page with no request

- GIVEN pages 1 to 3 have been loaded and page 2 is on screen after "Previous"
- WHEN the owner clicks "Next"
- THEN page 3's 5 rows are shown, the page number reads 3, and no request is made

#### Scenario: Previous is disabled on the first page

- GIVEN page 1 is on screen
- WHEN the section renders
- THEN "Previous" is disabled and still present, and clicking it changes nothing

#### Scenario: A failed request for the next page keeps the current page

- GIVEN page 1 is on screen with a `next_cursor` and the request for page 2 fails
- WHEN the owner clicks "Next"
- THEN page 1's 20 rows stay on screen, the page number reads 1, the panel says the next page could not be loaded, and "Next" is enabled; clicking it again repeats the request for page 2

#### Scenario: Another strategy starts on its first page

- GIVEN strategy S1's page 2 is on screen
- WHEN the owner opens strategy S2's detail view
- THEN S2's table shows its page 1 with the page number 1 and "Previous" disabled, and none of S1's rows

### Requirement: A Dry-Run Operation Is Marked By How It Was Filled

> **Added 2026-10-04 (owner decisions 43 and 45, design addendum "decision 43" § F).**

A row served as a rehearsal operation MUST carry a text tag on its own line in
the Pair cell, in the amber token of the dry-run mode badge, and its wording
MUST follow `rehearsal_fill_price`:

| `rehearsal_fill_price` | Tag, English | Tag, Spanish |
| --- | --- | --- |
| `FIXED_ONE` | Dry run · fixed price | Simulación · precio fijo |
| `ALERT` | Dry run · alert price | Simulación · precio de la alerta |
| `UNDETERMINED`, or a value the panel does not know | Dry run | Simulación |

Every cell of a rehearsal row MUST show the stored number: an entry of 1 and an
exit of 1 are printed as 1, and no cell is blanked or special-cased. Its PnL and
PnL % MUST be drawn in neutral ink, never in the gain or loss colour. A real
row is unmarked.

Below the table and its paging controls (owner decision 46, 2026-10-05; they sat under the table's title before) the panel MUST show a sentence for each of the
following conditions that is true of the rows of the page on screen (the one page shown, never
pages previously visited), and no
sentence whose condition is false:

1. at least one rehearsal row: "Operations marked "Dry run" were filled by the
   simulated exchange, not at the venue. They are not counted in any figure on
   this page." / "Las operaciones marcadas "Simulación" fueron ejecutadas por el
   exchange simulado, no en el exchange real. No se cuentan en ninguna cifra de
   esta página.";
2. at least one `FIXED_ONE` row: "A row marked "fixed price" was opened at a
   fixed price of 1, whatever the market price was. Its prices and its PnL are
   not a result." / "Una fila marcada "precio fijo" se abrió a un precio fijo de
   1, cualquiera fuera el precio de mercado. Sus precios y su PnL no son un
   resultado.";
3. at least one `ALERT` row: "A row marked "alert price" was opened at the price
   its alert carried. It was sized at 1x and its fee is simulated at the taker
   rate, so its PnL is not what it would have made live." / "Una fila marcada
   "precio de la alerta" se abrió al precio que traía su alerta. Se dimensionó a
   1x y su comisión es simulada a la tasa taker, así que su PnL no es el que
   habría dado en real." (the second sentence is the owner's wording of
   2026-10-05, follow-up 9qf.3).

An `UNDETERMINED` row, or one with a value the panel does not know, MUST get
sentence 1 only and no claim about its price. A strategy that only ran in dry
run therefore shows rows under a performance report that says zero trades, and
sentence 1 is what explains that.

#### Scenario: Each fill-price value shows its own tag

- GIVEN rows with `rehearsal_fill_price` `FIXED_ONE`, `ALERT` and `UNDETERMINED`
- WHEN the section renders in English
- THEN the tags read "Dry run · fixed price", "Dry run · alert price" and "Dry run", one each, each on its own line under the pair

#### Scenario: The tags in Spanish

- GIVEN the same rows and the locale Spanish
- WHEN the section renders
- THEN the tags read "Simulación · precio fijo", "Simulación · precio de la alerta" and "Simulación"

#### Scenario: A fixed-price row shows its stored numbers

- GIVEN a rehearsal row with entry price 1, exit price 1, fees 0 and PnL 0
- WHEN the row renders
- THEN its Entry and Exit cells print 1, its Fees cell prints 0, and no cell is blank

#### Scenario: A rehearsal row's PnL is neutral

- GIVEN a rehearsal row with a PnL of +3 USDT beside a real row with a PnL of +14.245 USDT
- WHEN the section renders
- THEN the rehearsal row's PnL and PnL % use neutral ink and the real row's use the gain colour

#### Scenario: The sentences follow the page on screen

- GIVEN page 1 holds a `FIXED_ONE` row and page 2 holds only real rows
- WHEN the owner moves from page 1 to page 2
- THEN sentences 1 and 2 are shown on page 1 and no sentence is shown on page 2

- GIVEN a page holding only real rows
- WHEN the section renders
- THEN none of the three sentences is shown

- GIVEN a page holding one `FIXED_ONE` row
- WHEN the section renders
- THEN sentences 1 and 2 are shown and sentence 3 is not

- GIVEN a page holding one `ALERT` row
- WHEN the section renders
- THEN sentences 1 and 3 are shown and sentence 2 is not

#### Scenario: An UNDETERMINED row gets the general sentence only

- GIVEN a page holding one `UNDETERMINED` row and no other rehearsal row
- WHEN the section renders
- THEN sentence 1 is shown and neither sentence 2 nor sentence 3 is

#### Scenario: A value the panel does not know reads as the plain tag

- GIVEN a row with `rehearsal_fill_price` `"SLIPPED"`
- WHEN the section renders
- THEN the row is tagged "Dry run" and only sentence 1 is shown

### Requirement: Each Operation Opens In A Detail Dialog

> **Added 2026-10-04 (owner decision 43, design addendum "decision 43" § F).**

Each row MUST carry a Details control that is a real button reachable with the
Tab key, opened with Enter or Space, whose visible text is "Details" / "Detalle"
and whose accessible name also names the pair, the side and the close time (for
example "Details of STXUSDT LONG, closed ..." / "Detalle de STXUSDT LONG,
cierre ..."). Opening it MUST show a modal dialog for that one operation, one at
a time, with focus moved into it. Its figures MUST be rendered from the row it
was opened from, with no request, and MUST NOT depend on the fills being
loaded. The dialog MUST show: the pair and the side (and the rehearsal tag when
it applies) in its title; opened and closed (UTC); entry price; exit price; size
with its base currency; fees paid in the settlement currency; fees in other
currencies when there are any; PnL; PnL % with a sentence saying it is measured
against the pool's capital at open and not against the position's margin; pool
capital at open; and the operation id (the allocation id). A rehearsal
operation's dialog MUST also show the sentence of its kind and say it is counted
in no total:

| `rehearsal_fill_price` | English | Spanish |
| --- | --- | --- |
| `FIXED_ONE` | Dry run at a fixed price: it was opened at a fixed price of 1, whatever the market price was. Its prices and its PnL are not a result. It is not counted in any total. | Simulación a precio fijo: se abrió a un precio fijo de 1, cualquiera fuera el precio de mercado. Sus precios y su PnL no son un resultado. No se cuenta en ningún total. |
| `ALERT` | Dry run at the alert's price: opened by the simulated exchange at the price its alert carried, not at the venue. It was sized at 1x and its fee is simulated at the taker rate, so its PnL is not what it would have made live. It is not counted in any total. | Simulación al precio de la alerta: abierta por el exchange simulado al precio que traía su alerta, no en el exchange real. Se dimensionó a 1x y su comisión es simulada a la tasa taker, así que su PnL no es el que habría dado en real. No se cuenta en ningún total. |
| `UNDETERMINED`, or unknown | Dry run: filled by the simulated exchange, not at the venue. It is not counted in any total. | Simulación: ejecutada por el exchange simulado, no en el exchange real. No se cuenta en ningún total. |

The PnL % sentence reads "PnL over the pool's capital when the operation opened,
not over the position's margin." / "PnL sobre el capital del pool al abrir la
operación, no sobre el margen de la posición.". A figure that is null in the row
MUST show the same em dash as the table. Escape or the dialog's Close button
("Close" / "Cerrar") MUST close it, and focus MUST return to the Details button
that opened it.

#### Scenario: The Details control is reachable by keyboard

- GIVEN a table of 20 rows
- WHEN the owner presses Tab until a Details control has focus and presses Enter, and in another attempt Space
- THEN the dialog for that row opens each time and focus is inside it

#### Scenario: Twenty Details controls have distinct names

- GIVEN a table of 20 rows
- WHEN the accessible names of the Details controls are listed
- THEN no two are equal, each naming its pair, side and close time

#### Scenario: The dialog shows every figure of the row with no request for them

- GIVEN a closed LONG on `STXUSDT` with entry 0.4512, exit 0.4631, size 1250 STX, fees 0.63 USDT, PnL 14.245 USDT, return `"0.0142450000"` and pool capital at open 1000 USDT
- WHEN its Details control is activated
- THEN the dialog shows "STXUSDT · LONG", both prices, "Size (STX)" 1250, "Fees paid (USDT)" 0.63, PnL, PnL %, the PnL % sentence, pool capital at open, and the allocation id, and no request is made for those figures

#### Scenario: A rehearsal operation's dialog says how it was filled

- GIVEN a `FIXED_ONE` rehearsal row
- WHEN its dialog opens in English
- THEN the title carries the tag "Dry run · fixed price" and the dialog shows the `FIXED_ONE` sentence of the table above

#### Scenario: A rehearsal operation's dialog in Spanish

- GIVEN an `ALERT` rehearsal row and the locale Spanish
- WHEN its dialog opens
- THEN it shows "Simulación al precio de la alerta: abierta por el exchange simulado al precio que traía su alerta, no en el exchange real. Se dimensionó a 1x y su comisión es simulada a la tasa taker, así que su PnL no es el que habría dado en real. No se cuenta en ningún total."

#### Scenario: Closing returns focus to the button

- GIVEN the dialog was opened from a row's Details control
- WHEN the owner presses Escape, and in another attempt activates Close
- THEN the dialog closes and `document.activeElement` is that row's Details control

#### Scenario: Only one dialog is open at a time

- GIVEN a dialog is open
- WHEN the owner opens another operation
- THEN the first has closed and only the second is shown

### Requirement: The Detail Dialog Shows The Operation's Fills

> **Added 2026-10-04 (owner decision 43, answered 2026-10-04).**

The dialog MUST show, under the figures, a table captioned "Fills" /
"Ejecuciones" with one line per fill served by the fills route: Time (UTC),
Side ("Buy" / "Compra" or "Sell" / "Venta"), Price, Quantity with the base
currency, and Fee with its amount and currency. The panel MUST NOT request the
fills until the dialog is opened, MUST make that request when it opens, and MUST
NOT prefetch the fills of any row. The table MUST be a real table inside the
dialog's own scrolling body.

An operation whose figures cannot be derived has no base currency. Its dialog
MUST still open, and the two headings that carry the base currency MUST then
read without the parenthesis: "Size" / "Tamaño" in the figures and "Quantity" /
"Cantidad" in the fills table. No currency is guessed from the pair (owner's
answer of 2026-10-05).

The table MUST be in one of these states:

- loading: "Loading the fills…" / "Cargando las ejecuciones…";
- loaded: the table, and, when the response says `truncated`, one sentence
  "Only the first 200 fills are shown." / "Solo se muestran las primeras 200
  ejecuciones.";
- failed: "The fills could not be loaded." / "No se pudieron cargar las
  ejecuciones." with a "Try again" / "Reintentar" button in the dialog's tab
  order, and the dialog's figures still on screen.

A fill whose rehearsal flag differs from the operation's own mark MUST carry
the "Dry run" / "Simulación" tag on its line. A response MUST be refused, as a
failure and with no partial table, when a field is missing or mistyped, when
`side` is neither BUY nor SELL, when the list is empty, or when its
`allocation_id` is not the one asked for.

#### Scenario: No fills are requested until an operation is opened

- GIVEN a page of 20 rows
- WHEN the section renders and the owner has not opened any operation
- THEN no fills request has been made

#### Scenario: Opening an operation requests its fills

- GIVEN a row with allocation id A1
- WHEN the owner opens its dialog
- THEN one fills request is made for A1 and the loading line shows until it answers

#### Scenario: The fills table lists each fill

- GIVEN A1's fills are a BUY of 1250 at 0.4512 with fee 0.31 USDT and a SELL of 1250 at 0.4631 with fee 0.32 USDT
- WHEN the dialog's fills load, in English
- THEN the table shows two lines in that order, the first with Side "Buy", Price 0.4512, Quantity 1250 and Fee "0.31 USDT"

#### Scenario: A truncated list says so

- GIVEN a fills response with `truncated` true
- WHEN the table renders
- THEN the sentence "Only the first 200 fills are shown." is shown

#### Scenario: A failed read keeps the figures

- GIVEN the fills request answers 404, or fails, or the route does not exist on an older API
- WHEN the dialog shows its fills
- THEN it shows "The fills could not be loaded." with "Try again", the figures are still on screen, and activating "Try again" repeats the request

#### Scenario: A malformed body is an error, never a partial table

- GIVEN a fills response whose `allocation_id` is not the one asked for, or with an empty list, or with a `side` of "HOLD", or with a `price` that is a number
- WHEN the dialog handles it
- THEN it shows the failed state and draws no line of the table

#### Scenario: A fill of the other origin is tagged

- GIVEN a mixed allocation whose operation is a real row and whose fills hold one with `rehearsal` true
- WHEN the fills table renders
- THEN that line carries the "Dry run" tag and the others do not

### Requirement: The Trades Section Refuses What It Cannot Show Truthfully

> **Added 2026-10-04 (design addendum "decision 43" § G).**

The trades section MUST refuse a whole page, and show its error state with a
"Try again" control while the rest of the strategy page keeps working, when any
row of the page lacks `rehearsal`, `fees` or `other_fees`, carries a value of
the wrong type in any field it checks, has `rehearsal_fill_price` null on a
rehearsal row, or has it set on a real row. No row of a refused page MUST be
rendered. A page refused because the API predates the new fields MUST end when
the API serves them and the owner chooses "Try again".

#### Scenario: A row missing a new field refuses the page

- GIVEN a page of 20 rows in which one row lacks `fees`
- WHEN the section handles it
- THEN no row is rendered, the section shows its error state with "Try again", and the rest of the strategy page renders

#### Scenario: A number where a string is due refuses the page

- GIVEN a row whose `size` is the JSON number 1250
- WHEN the section handles the page
- THEN the page is refused as above

#### Scenario: Contradictory marker fields refuse the page

- GIVEN a row with `rehearsal` true and `rehearsal_fill_price` null, and in another page a row with `rehearsal` false and `rehearsal_fill_price` `"ALERT"`
- WHEN the section handles each page
- THEN each page is refused as above

#### Scenario: An older API's rows refuse the page without crashing

- GIVEN the API serves rows with the original nine fields only
- WHEN the section handles the page
- THEN it shows its error state with "Try again" and no row with an invented figure

#### Scenario: The retry loads the page once the API is current

- GIVEN a refused page and the API now serving the new fields
- WHEN the owner chooses "Try again"
- THEN the page loads and its rows render

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

### Requirement: Deleting A Strategy Requires Explicit Confirmation And States Its Refusal

> **Added 2026-10-02 (owner decision 42).**

The strategy detail view MUST offer a delete control, separate from the enable
and archive controls. Using it MUST require an explicit confirmation step in
which the owner types the strategy's name; no delete request MUST be sent
before the typed text equals that name, and a single click MUST never send
one. The confirmation MUST state that the delete cannot be undone.

The control MUST be unavailable while the strategy is enabled, and MUST say
that the strategy has to be disabled first.

A refused delete MUST show the specific reason: that the strategy is still
enabled, or that it has history, naming each kind of history that exists with
its count and stating that archiving is the remaining option. A count is a
number of rows; the panel MUST NOT present any of them as an amount of money
or sum anything across capital pools.

After a successful delete the panel MUST return to the Strategies list, and
the deleted strategy MUST no longer appear there, with or without archived
strategies shown. A delete answered as "not found" MUST be treated the same
way, because the strategy is already gone.

> **Open (design addendum 9x § L, Q3).** Whether the control is offered for an
> archived strategy follows the owner's answer.

#### Scenario: Delete is not triggered by a single click

- GIVEN strategy S1 is disabled and has no history
- WHEN the owner clicks delete once
- THEN a confirmation is shown and no delete request has been sent

#### Scenario: The confirmation is inert until the name is typed

- GIVEN the delete confirmation for strategy "Test A" is open
- WHEN the owner types "Test" and attempts to confirm
- THEN no delete request is sent
- WHEN the owner types "Test A" and confirms
- THEN the delete request is sent

#### Scenario: Cancelling sends nothing

- GIVEN the delete confirmation for strategy S1 is open
- WHEN the owner cancels it
- THEN no delete request is sent and S1's detail view is unchanged

#### Scenario: The control is unavailable while the strategy is enabled

- GIVEN strategy S1 is enabled
- WHEN S1's detail view renders
- THEN the delete control cannot be used and states that S1 must be disabled first

#### Scenario: A refusal for history names each kind and its count

- GIVEN strategy S1 on pool `(bybit, usdt-m, USDT)` is disabled and has 3 signals and 2 ledger entries
- WHEN the owner confirms deleting S1
- THEN the panel shows that S1 has history and cannot be deleted, names 3 signals and 2 ledger entries, names no kind whose count is zero, and states that S1 can be archived instead

#### Scenario: A successful delete returns to the list

- GIVEN strategy S1 is disabled and has no history
- WHEN the owner confirms deleting S1 and the delete succeeds
- THEN the panel shows the Strategies list and S1 is not in it, including when archived strategies are shown

#### Scenario: A strategy already deleted elsewhere is treated as deleted

- GIVEN strategy S1's detail view is open and S1 was deleted by another request
- WHEN the owner confirms deleting S1
- THEN the panel returns to the Strategies list without showing an error

#### Scenario: The delete flow renders under both locales

- GIVEN the locale is set to Spanish
- WHEN the delete control, its confirmation and a refusal render
- THEN every visible string is in Spanish, sourced from i18n

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

### Requirement: Allowed Pairs Are Chosen From The Pool's Available Pairs

> **Added 2026-10-02 (owner decisions 40 and 41).** Replaces the free-text
> pairs input of the new-strategy dialog. The strategy detail's allowed-pairs
> editor (the requirement above) uses the same selector.

Wherever the panel lets the owner set a strategy's allowed pairs, it MUST
offer a searchable selection among the pairs available to that strategy's
capital pool `(exchange, venue, settlement_currency)`, read from the admin
API, and MUST NOT offer a free-text field in which an arbitrary symbol can be
submitted. The selector MUST:

- be operable with the keyboard alone and expose a label for the search field,
  for every option and for every remove control;
- show nothing selectable until a pool is chosen, and clear the selection when
  the pool changes;
- show a loading state while the available pairs are being read, and a failure
  state with a retry control when they cannot be read, and MUST NOT fall back
  to free text in either;
- when many pairs match, show a bounded number of them and say how many match;
- find a pair when the owner types it in another spelling of the same market;
- keep showing a selected pair that the venue no longer lists, marked as no
  longer listed, until the owner removes it, and MUST NOT drop it silently.

When a save is refused, the panel MUST state the reason: the symbols the
exchange does not list, by name; or that the exchange's pair list could not be
read and nothing was saved. Every string MUST be localized EN/ES.

#### Scenario: The new-strategy dialog offers the pool's pairs, not free text

- GIVEN the owner opens the new-strategy dialog and chooses pool `(bybit, usdt-m, USDT)`, whose available pairs include `STXUSDT`
- WHEN the pairs field renders
- THEN it is a searchable selection over that pool's available pairs, and no free-text pairs field exists

#### Scenario: Nothing is selectable before a pool is chosen

- GIVEN the owner opens the new-strategy dialog and has not chosen a pool
- WHEN the pairs field renders
- THEN it offers no pair and says a pool must be chosen first

#### Scenario: Typing another spelling finds the pair

- GIVEN pool `(bybit, usdt-m, USDT)` whose available pairs include `STXUSDT`
- WHEN the owner types `stxusdt.p` in the search field
- THEN `STXUSDT` is offered, and selecting it submits `STXUSDT`

#### Scenario: A selection is made with the keyboard alone

- GIVEN pool `(bybit, usdt-m, USDT)` whose available pairs are offered
- WHEN the owner moves focus to a pair and toggles it with the keyboard
- THEN the pair is selected and appears among the selected pairs with a labelled remove control

#### Scenario: Changing the pool clears the selection

- GIVEN the owner selected `STXUSDT` for pool `(bybit, usdt-m, USDT)`
- WHEN the owner changes the pool to `(binance, usdt-m, USDT)`
- THEN no pair is selected and the offered pairs are those of pool `(binance, usdt-m, USDT)`

#### Scenario: Available pairs that cannot be read show a failure, not free text

- GIVEN the available pairs of pool `(binance, usdt-m, USDT)` cannot be read
- WHEN the pairs field renders
- THEN it shows a failure message with a retry control, offers no free-text field, and the new-strategy dialog cannot be submitted

#### Scenario: Many matches are bounded and counted

- GIVEN pool `(bybit, usdt-m, USDT)` has several hundred available pairs
- WHEN the owner types `USDT`
- THEN a bounded number of matches is shown together with the number that match

#### Scenario: A stored pair the venue no longer lists stays visible

- GIVEN strategy S1 on pool `(bybit, usdt-m, USDT)` has allowed pairs `{ETHUSDT, SFPUSDT}` and that pool's available pairs no longer include `SFPUSDT`
- WHEN S1's allowed-pairs editor renders
- THEN `SFPUSDT` is shown as selected and marked as no longer listed, and saving without touching it sends `{ETHUSDT, SFPUSDT}`

#### Scenario: A refusal for an unlisted symbol names it

- GIVEN a save was refused with `UNKNOWN_PAIRS` naming `YPF`
- WHEN the refusal is shown
- THEN the message names `YPF`

#### Scenario: A refusal for an unreachable exchange says so

- GIVEN a save was refused because the pair list of pool `(binance, usdt-m, USDT)` could not be read
- WHEN the refusal is shown
- THEN the message says the exchange's pair list could not be read and that nothing was saved, and it does not say the pairs were wrong

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
owner leaves the view. (Unit 12f, 2026-10-06, owner decisions 44 and 48: the
URL shown carries the webhook's host when one is available, and two Copy
buttons are offered, as "The Webhook URL Is Shown And Copied With Its Host" and
"The Webhook Block Has Two Copy Buttons" describe. Neither Copy button is the
explicit "Show secret" action, and neither reveals the secret. Revised
2026-10-10, owner decision 53: with the secret hidden, "Copy URL" asks the server
for it at the click, to write the URL that works, and shows nothing of it; the
secret stays REVEALED only by "Show secret".)

#### Scenario: Webhook message is copy-ready with a placeholder by default

- GIVEN strategy S1's detail view is open
- WHEN it renders
- THEN a copy-ready webhook message is shown, and the webhook URL carries a placeholder instead of the shared secret

#### Scenario: No action other than the explicit request reveals the secret

- GIVEN strategy S1's detail view is open
- WHEN the owner uses any control in the view other than "Show secret"
- THEN the shared secret is never displayed, and it is never requested from the server except by "Copy URL" while the secret is hidden (decision 53), which displays nothing of it

#### Scenario: The explicit request reveals the secret in place

- GIVEN strategy S1's detail view is open and the webhook URL shows the placeholder
- WHEN the owner clicks "Show secret"
- THEN the panel requests the secret from `GET /api/webhook-secret` and substitutes it into the URL in place of the placeholder

#### Scenario: Leaving the view hides the secret again

- GIVEN the secret is currently revealed in strategy S1's detail view
- WHEN the owner navigates away from that view
- THEN the placeholder is restored and the revealed value is no longer retained in the panel's state

### Requirement: The Share Of The Pool Per Trade Is Shown And Edited In The Settings Column Only

> **Added 2026-10-06 (owner decisions 44 and 48; design addendum "unit 12f").**

The strategy detail view MUST show the strategy's share of the pool per trade
and MUST let the owner edit it, in the page's settings column and nowhere else.
The control MUST be the first of the column, under its heading and above the
allowed pairs, labelled "Share of the pool per trade" / "Porcentaje del pool por
operación". The share MUST NOT be printed in the page's header line, and MUST NOT
be shown in a row of the Strategies list. The share is a share of the pool's
TOTAL balance, in the strategy's own pool `(exchange, venue,
settlement_currency)`, not of what is free; the text behind the label's
information button says so.

#### Scenario: The share is the first control of the settings column

- GIVEN strategy S1 on pool `(bybit, usdt-m, USDT)` with a stored share of `30`
- WHEN S1's detail view renders
- THEN the settings column shows the share control, labelled "Share of the pool per trade", above the allowed-pairs control and below the column's heading

#### Scenario: The share is not printed in the header line

- GIVEN strategy S1 with a stored share of `30`
- WHEN S1's detail view renders
- THEN no text of the page's header line contains "30%" or the word "per trade"

#### Scenario: The Strategies list does not show the share

- GIVEN strategies S1 and S2 with stored shares `30` and `100`
- WHEN the Strategies list renders
- THEN no row shows either share

### Requirement: The Share Control Is A Field Above A Track With Four Stops

> **Added 2026-10-06 (owner decision 48, answered 2026-10-06 and approved on the third prototype).**

The share control MUST be laid out top to bottom on the full width of the
column: the label with its information button; the field; the track with its
handle; the legend of four stops; the amount the share asks for with its
information button, and under it the warning of "A Share That Asks For Less Than
The Pool's Minimum Order Is Warned About And Never Blocked" when it applies; the
validation or refusal text; and the Save button, which reads "Saved" itself after a save.
No explanatory paragraph MUST be on screen.

- **The field** holds the number and its percent sign together at the left. The
  sign MUST follow the last character typed, MUST NOT be part of the field's
  value, and MUST NOT count against the field's length. Typing `%` is not a
  number. In a browser that cannot size a field to its text, the sign MAY stand
  about one character off the number; it MUST still be at the left, right after
  the number.
- **The track** runs from 1 to 100 in whole steps of 1. It MUST NOT start at 0.
- **The stops** are marked at 25, 50, 75 and 100. Each reads as a legend label
  ("25%") and MUST be activatable: activating one sets the share to that value.
- **One value.** The track and the field MUST always show the same value. The
  handle sits at the value rounded half up to a whole number and clamped to 1
  to 100.
- **Decimals.** A stored value with decimals MUST be shown as stored, in the
  field, in both languages with a dot. The value MUST be rounded to a whole
  number only when the owner moves the handle (or presses an arrow key on it),
  never on load and never by typing.
- **A value below 1** is valid; the handle then sits at the start of the track.
- **Moving the handle**, by pointer or key, or activating a stop, sets the field
  to that whole number. **Typing** a value that reads as valid moves the handle to
  it; typing one that does not leaves the handle where it was.

#### Scenario: A stored value with decimals is shown as it is

- GIVEN strategy S1 on pool `(bybit, usdt-m, USDT)` has a stored share of `33.5`
- WHEN its detail view renders
- THEN the field shows `33.5` with the percent sign right after it, the handle sits at step 34, and the stop labelled "25%" and the stop labelled "50%" are not marked as the value

#### Scenario: A stored value below 1 leaves the handle at the start

- GIVEN a stored share of `0.5`
- WHEN the detail view renders
- THEN the field shows `0.5` and the handle sits at the start of the track, step 1

#### Scenario: The handle rounds only when it is moved

- GIVEN a stored share of `33.5`, the handle at step 34
- WHEN the owner presses the right arrow once on the track
- THEN the field shows `35`, and from the same start one press of the left arrow shows `33`

#### Scenario: Activating a stop sets that value

- GIVEN the field shows `33.5`
- WHEN the owner activates the stop "75%"
- THEN the field shows `75`, the handle sits at step 75, and that stop is marked as the current value

#### Scenario: Typing a valid decimal moves the handle

- GIVEN the handle is at step 34
- WHEN the owner types `62.5` in the field
- THEN the field holds exactly `62.5` and the handle sits at step 63

#### Scenario: Typing an invalid text leaves the handle where it was

- GIVEN the field holds `62.5` and the handle sits at step 63
- WHEN the owner types `62.5x`
- THEN the field holds exactly `62.5x` and the handle still sits at step 63

#### Scenario: The sign is not part of the value

- GIVEN the field shows `33.5`
- WHEN the field's value is read
- THEN it is `33.5`, and typing `%` into the field marks it as not a number

#### Scenario: The track does not start at 0

- GIVEN the share control is on screen
- WHEN the track is read
- THEN its smallest step is 1 and its largest is 100

### Requirement: The Share Field Accepts An Exact Value And Refuses What Is Not One

> **Added 2026-10-06 (owner decision 48, design addendum "unit 12f" § C).**

The share field MUST accept an exact value above 0 and at most 100, decimals
included, and MUST keep the text as typed. A comma MUST be read as the decimal
separator (one comma only) and the value MUST be sent with a dot. The field's
length MUST be bounded at 12 characters. The panel MUST validate before it
sends, and MUST refuse, with Save disabled, each of these classes:

- **Zero**: `0`, `0.0`. Text: "The share must be above 0 and at most 100." /
  "El porcentaje debe ser mayor que 0 y como máximo 100."
- **Above 100**: `100.5`, `150`. The same text.
- **Not a number**: an empty field, `abc`, `1e1`, `-5`, `25%`, `1.000,5`, `33.`.
  Text: "Enter a number, for example 25 or 33.5." / "Escriba un número, por
  ejemplo 25 o 33,5." Nothing MUST be guessed and nothing trimmed into a value.
- **Too many decimals** (owner decision 50): a value whose canonical form, without
  trailing zeros, has more than 18 decimal places, such as `33.3333333333333333333`
  (19). Text: "A share has at most 18 decimal places." / "El porcentaje tiene como
  máximo 18 decimales." It is judged after the three above. No preview and no save
  MUST be sent for it.

Typing back the stored value MUST be valid and unchanged, with Save disabled.
The refusal text MUST be tied to the field and the field MUST be marked invalid;
the text MUST NOT be announced as an alert on every keystroke.

#### Scenario: A decimal with a dot is accepted

- GIVEN the field holds `25`
- WHEN the owner types `33.5`
- THEN no refusal text shows and Save is enabled

#### Scenario: A comma is read as the decimal separator

- GIVEN a stored share of `25`
- WHEN the owner types `33,5` and presses Save
- THEN the field keeps showing `33,5` while typed, and the request body carries `"allocation_percent": "33.5"`

#### Scenario: A value below 1 is accepted

- GIVEN a stored share of `25`
- WHEN the owner types `0.5`
- THEN no refusal text shows, Save is enabled and the handle sits at step 1

#### Scenario: Exactly 100 is accepted

- GIVEN a stored share of `25`
- WHEN the owner types `100`
- THEN no refusal text shows and Save is enabled

#### Scenario: Zero is refused

- GIVEN a stored share of `25`
- WHEN the owner types `0`, and then `0.0`
- THEN each time "The share must be above 0 and at most 100." shows, the field is marked invalid, and Save is disabled

#### Scenario: A value above 100 is refused

- GIVEN a stored share of `25`
- WHEN the owner types `100.5`, and then `150`
- THEN each time "The share must be above 0 and at most 100." shows and Save is disabled

#### Scenario: A value of more than 18 decimal places is refused

- GIVEN a stored share of `25`
- WHEN the owner types `33.3333333333333333333` (19 decimals)
- THEN "A share has at most 18 decimal places." shows, the field is marked invalid, Save is disabled and no preview and no save request is sent
- AND `0.123456789012345678` (18 decimals) and `1.5000000000000000000` (which is `1.5`) are accepted

#### Scenario: An empty field is refused as not a number

- GIVEN a stored share of `25`
- WHEN the owner clears the field
- THEN "Enter a number, for example 25 or 33.5." shows, Save is disabled and no value is substituted

#### Scenario: Text that is not a plain decimal is refused

- GIVEN a stored share of `25`
- WHEN the owner types, one at a time, `abc`, `1e1`, `-5`, `25%`, `1.000,5` and `33.`
- THEN each time "Enter a number, for example 25 or 33.5." shows and Save is disabled

#### Scenario: The refusal text is not an alert

- GIVEN the owner is typing `33.5` one character at a time
- WHEN the field passes through the refused text `33.`
- THEN the refusal text is tied to the field as its description and is not a live alert, so a screen reader does not announce it on that keystroke

#### Scenario: Typing the stored value back is unchanged

- GIVEN a stored share of `33.5` and the owner has changed the field to `40`
- WHEN the owner types `33.5` again
- THEN no refusal text shows and Save is disabled

#### Scenario: A long paste is cut at 12 characters

- GIVEN the field is empty
- WHEN the owner pastes a text of 20 digits
- THEN the field holds at most 12 characters

### Requirement: The Share Is Saved Only Through An Explicit Save Button

> **Added 2026-10-06 (owner decisions 44 and 48; design addendum "unit 12f" § C).**

Moving the handle, activating a stop, or typing MUST change only what the panel
shows; nothing MUST be sent until the owner activates Save, and leaving the page
without saving MUST keep the stored value. Save MUST be enabled only when the
strategy is not archived, no save is in flight, the field reads as a value above
0 and at most 100, and that value, in plain form, differs from the stored one. A
save MUST be one `PATCH /api/strategies/{id}` whose body is exactly
`{"allocation_percent": "<value>"}`, the value a string, with no other field.
A stored value MUST be read in plain form (`33.50` is `33.5`, `100.000` is
`100`); a draft made on a stored value MUST be dropped when the stored value
moves.

The control MUST show these states:

| State | What shows |
| --- | --- |
| Unchanged | The stored value; Save disabled |
| Changed, not saved | The new value; Save enabled |
| Saving | Save reads "Saving…" / "Guardando…"; the track, the stops and the field are disabled |
| Saved | The value the server answered, and "Saved" (see "A Save Of The Share Or Of The Allowed Pairs Shows \"Saved\"") |
| Refused 422 | "The share must be above 0 and at most 100." |
| Refused 409 `STRATEGY_ARCHIVED` | "This strategy is archived and can no longer be changed."; the page reads the strategy again and the control turns read-only |
| Refused 404 | "This strategy no longer exists."; the page shows its not-found state |
| A network failure, a 5xx, or a 200 whose body is not a strategy | "The share was not saved. Try again."; the draft is kept |
| An archived strategy | The value shown; the track, the stops, the field and Save disabled; the information buttons still enabled |
| A stored value that cannot be read | "The stored share could not be read, so it cannot be edited here."; no track, no field, no Save, never a guess |

Each refusal MUST be an alert line, and a refused save MUST NOT show "Saved". A
401 MUST be handled as on every other call: the token is cleared and the token
gate takes over.

#### Scenario: Nothing is sent before Save

- GIVEN a stored share of `30`
- WHEN the owner moves the handle to 40, activates the stop "75%", types `12.5`, and then leaves the page without pressing Save
- THEN no request was sent, and the strategy's stored share is still `30` when its page is opened again

#### Scenario: Save sends exactly the share, as a string

- GIVEN a stored share of `30` and the field holds `33.5`
- WHEN the owner presses Save
- THEN one `PATCH /api/strategies/{id}` is sent with the body `{"allocation_percent": "33.5"}` and no other field

#### Scenario: Save is disabled while nothing changed

- GIVEN a stored share of `33.50` served by the API
- WHEN the detail view renders
- THEN the field shows `33.5` and Save is disabled

#### Scenario: Save is disabled for an invalid value

- GIVEN a stored share of `30`
- WHEN the field holds `0`
- THEN Save is disabled

#### Scenario: A save in flight disables the control

- GIVEN the owner pressed Save and the answer has not arrived
- WHEN the control is read
- THEN Save reads "Saving…" and the track, the stops and the field are disabled

#### Scenario: A successful save shows the confirmed value

- GIVEN the owner saved `33.5` and the API answered 200 with a strategy whose share is `33.5`
- WHEN the control is read
- THEN the field shows `33.5`, Save is disabled and "Saved" shows

#### Scenario: A 422 is shown with its text

- GIVEN the owner pressed Save and the API answered 422
- WHEN the control is read
- THEN "The share must be above 0 and at most 100." shows as an alert, no "Saved" shows, and the draft is kept

#### Scenario: A 409 turns the control read-only

- GIVEN the owner pressed Save and the API answered 409 `STRATEGY_ARCHIVED`
- WHEN the page has read the strategy again
- THEN "This strategy is archived and can no longer be changed." shows, and the track, the stops, the field and Save are disabled

#### Scenario: A 404 shows the not-found state

- GIVEN the owner pressed Save and the API answered 404
- WHEN the control is read
- THEN "This strategy no longer exists." shows and the page shows its not-found state

#### Scenario: A failure keeps the draft

- GIVEN the owner pressed Save with `33.5` and the API answered 500
- WHEN the control is read
- THEN "The share was not saved. Try again." shows as an alert, the field still holds `33.5`, Save is enabled and no "Saved" shows

#### Scenario: A 200 whose body is not a strategy is a failure

- GIVEN the owner pressed Save and the API answered 200 with a body that is not a strategy
- WHEN the control is read
- THEN "The share was not saved. Try again." shows and no "Saved" shows

#### Scenario: An archived strategy's share is read-only

- GIVEN strategy S1 is archived with a stored share of `30`
- WHEN its detail view renders
- THEN the field shows `30`, and the track, the four stops, the field and Save are disabled, and both information buttons are enabled

#### Scenario: A stored value that cannot be read is never guessed

- GIVEN the API serves a stored share whose text is `1E+1`
- WHEN the detail view renders
- THEN "The stored share could not be read, so it cannot be edited here." shows, and no track, no field and no Save are present

#### Scenario: A draft is dropped when the stored value moves

- GIVEN the owner typed `40` on a stored `30`, and the strategy is then re-read with a stored `55`
- WHEN the control is read
- THEN the field shows `55` and Save is disabled

### Requirement: The Amount The Share Asks For Is Computed By The Server And Shown Under The Track

> **Added 2026-10-06 (owner decision 48, answered 2026-10-06; design addendum "unit 12f" § C2).**

Under the track the control MUST show the amount the share in the field asks for
per operation, in the settlement currency of the strategy's own pool
`(exchange, venue, settlement_currency)`, as "Asks for about {amount}
{currency} per operation" / "Pide alrededor de {amount} {currency} por
operación". The amount MUST be the figure the server served from
`GET /api/strategies/{id}/share-preview`; the panel MUST NOT compute it, and in
particular MUST NOT multiply a pool's balance by the share, whatever balance the
panel holds from another read. The figure MUST be written with the pool
currency's own decimals, as the PnL and fees of the trades table are (two for
USDT), and MUST be cut down to them as text, never rounded up. A time the panel
names (the balance's read) MUST be written `HH:MM UTC`. An amount is never summed or converted across
pools. The row, with its information button, MUST always be present.

Which amount is shown, and when a request is made:

- A whole number from 1 to 100 (every handle position, every stop): from the
  table of the hundred whole steps already read. NO request MUST be made while the
  handle is dragged or a stop activated, and the figure MUST follow the handle at
  once.
- The stored share, when it has decimals: from the first read, with no further
  request.
- Any other valid value (a typed decimal, or a value below 1): one request,
  sent after a pause (300 ms after the last keystroke), with `share` set to the
  value. While it is pending the line MUST show a loading mark and NO figure,
  never the previous one beside the new percentage. An answer MUST be used only
  when it is for the share asked, compared in plain form.
- A text that is not a valid value: no request.
- The preview MUST be read when the control mounts and again every 60 seconds.
- A body that fails the panel's check (`balance`, `exact` and `steps` not all
  present or all absent; `steps` not exactly the hundred steps numbered 1 to 100
  in order; an amount that is not a string) MUST be an error, never a partial
  table.

| State of the amount | What shows under the track |
| --- | --- |
| Known | The amount and its currency |
| The balance is stale | The same, with "The pool's balance was last read at {time} UTC and may be out of date." |
| The pool has no balance yet | "The pool's balance has not been read yet, so the amount cannot be shown." and no figure, never a zero |
| Loading (the first read, or a typed decimal's) | "Calculating the amount…", no figure |
| The read failed, or its body was refused | "The amount could not be loaded." |
| The field holds no valid value | An em dash where the figure would be |

None of these states MUST disable the track, the stops, the field or Save: the
amount is information, and its failure MUST NOT stop a save.

#### Scenario: A known amount is shown from the server's figure

- GIVEN strategy S1 on pool `(bybit, usdt-m, USDT)` with a stored share of `33.5`, and the preview answers a total of 1000 USDT with `exact.amount` `335.000000000000000000`
- WHEN the detail view renders
- THEN under the track the line reads "Asks for about 335.00 USDT per operation"

#### Scenario: Dragging the handle makes no request and the figure follows

- GIVEN the preview was read with a total of 1000 USDT and the handle sits at step 20
- WHEN the owner drags the handle to step 80
- THEN no request is made, and the line reads "Asks for about 800.00 USDT per operation" at step 80

#### Scenario: A stop's amount comes from the table already read

- GIVEN the preview was read with a total of 1000 USDT
- WHEN the owner activates the stop "25%"
- THEN the line reads "Asks for about 250.00 USDT per operation" and no request is made

#### Scenario: A typed decimal asks once after a pause and shows no figure meanwhile

- GIVEN the line reads "Asks for about 335.00 USDT per operation" for `33.5`
- WHEN the owner types `12.34`
- THEN the line shows "Calculating the amount…" and no figure (at no moment does 335.00 stand beside 12.34), exactly one request with `share=12.34` is sent 300 ms after the last keystroke, and its answer `123.400000000000000000` then reads "Asks for about 123.40 USDT per operation"

#### Scenario: An answer for a value the field no longer holds is not used

- GIVEN a request for `12.34` is in flight
- WHEN the owner changes the field to `12.35` and the answer for `12.34` then arrives
- THEN that answer is not shown, and the line shows the loading mark or the figure of `12.35`

#### Scenario: A value below 1 asks for its own amount

- GIVEN the preview was read with a total of 1000 USDT
- WHEN the owner types `0.5`
- THEN one request with `share=0.5` is made after the pause, and its answer `5.000000000000000000` reads "Asks for about 5.00 USDT per operation"

#### Scenario: A stored value with decimals needs no second request

- GIVEN a stored share of `33.5`
- WHEN the detail view renders and the first preview answers
- THEN the figure comes from that answer's `exact` and no request with `share` is made

#### Scenario: The figure is cut down, never rounded up

- GIVEN the preview answers an amount of `4.999999999999999999` USDT for pool `(bybit, usdt-m, USDT)`
- WHEN the line renders
- THEN it reads "Asks for about 4.99 USDT per operation", not 5.00

#### Scenario: Cutting and rounding differ

- GIVEN pool `(bybit, usdt-m, USDT)` has a total of `1000.999` USDT, a share of `50`, and the server answers `500.499500000000000000`
- WHEN the line renders
- THEN it reads "Asks for about 500.49 USDT per operation", not 500.50

#### Scenario: The panel never multiplies a balance it holds

- GIVEN the pools read shows a total of 900 USDT for pool `(bybit, usdt-m, USDT)` and the preview answers 335.00 for a share of `33.5` at a total of 1000 USDT
- WHEN the line renders
- THEN it reads "Asks for about 335.00 USDT per operation"

#### Scenario: A stale balance is shown, marked

- GIVEN the preview answers a balance with `stale` true and `observed_at` 14:03 UTC
- WHEN the line renders
- THEN the amount shows, and "The pool's balance was last read at 14:03 UTC and may be out of date." shows with both information buttons closed

#### Scenario: A pool never read shows no figure

- GIVEN the preview answers `balance` null, `exact` null and `steps` empty
- WHEN the line renders
- THEN "The pool's balance has not been read yet, so the amount cannot be shown." shows, no figure and no zero shows, and the handle, the field and Save remain usable

#### Scenario: A failed preview does not stop the save

- GIVEN the preview fails with a 500
- WHEN the owner moves the handle to 40 and presses Save
- THEN "The amount could not be loaded." shows, the track, the stops and the field are not disabled, and Save sends `{"allocation_percent": "40"}`

#### Scenario: A body that fails the panel's check is an error

- GIVEN the preview answers a body whose `steps` holds 99 entries
- WHEN the line renders
- THEN "The amount could not be loaded." shows and no figure from that body shows

#### Scenario: An invalid value shows an em dash

- GIVEN the field holds `abc`
- WHEN the line renders
- THEN an em dash stands where the figure would be, the row's information button is present, and no request is made

#### Scenario: The amount is re-read every minute

- GIVEN the control has been on screen for 60 seconds
- WHEN the interval elapses
- THEN the preview is read again

### Requirement: A Share That Asks For Less Than The Pool's Minimum Order Is Warned About And Never Blocked

> **Added 2026-10-06 (owner decision 48, answered 2026-10-06; design addendum "unit 12f" § C3).**

When the preview says the amount of the value in the field is below the pool's
own minimum order (`below_pool_minimum` true), one line under the amount MUST say
so: "At this balance the share asks for less than the pool's minimum order,
{minimum} {currency}. Openings would be skipped until the share or the balance is
larger." / "Con este saldo, el porcentaje pide menos que la orden mínima del
pool, {minimum} {currency}. Las aperturas se omitirían hasta que el porcentaje o
el saldo sean mayores." The line MUST always be visible, not behind an
information button; MUST show on the STORED value as well as on a change; MUST be
a status line, not an alert; and MUST be in the colour of refusals. It MUST make
no claim about a later balance. It MUST NEVER disable Save, the field or the
track: a value below 1% is allowed, and so is a value under the minimum. The
minimum is the pool's own, in its settlement currency, and is not the exchange's
minimum for any pair.

#### Scenario: A share asking for less than the minimum shows the warning

- GIVEN pool `(bybit, usdt-m, USDT)` has a balance of 300 USDT and a minimum order of 5 USDT
- WHEN the field holds `1`, so the share asks for 3 USDT
- THEN "At this balance the share asks for less than the pool's minimum order, 5.00 USDT. Openings would be skipped until the share or the balance is larger." shows with both information buttons closed

#### Scenario: A share above the minimum shows no warning

- GIVEN pool `(bybit, usdt-m, USDT)` has a balance of 300 USDT and a minimum order of 5 USDT
- WHEN the field holds `2`, so the share asks for 6 USDT
- THEN no warning shows

#### Scenario: An amount exactly at the minimum is not warned about

- GIVEN pool `(bybit, usdt-m, USDT)` has a balance of 500 USDT and a minimum order of 5 USDT
- WHEN the field holds `1`, so the share asks for exactly 5 USDT
- THEN no warning shows

#### Scenario: The stored value is warned about on load

- GIVEN a stored share of `1` on pool `(bybit, usdt-m, USDT)` with a balance of 300 USDT and a minimum order of 5 USDT, and the owner has changed nothing
- WHEN the detail view renders
- THEN the warning shows

#### Scenario: A balance that falls puts the warning on a stored share

- GIVEN a stored share of `2`, shown with a balance of 300 USDT (6 USDT, no warning), and the next read of the preview answers a balance of 200 USDT
- WHEN the line renders again
- THEN the amount reads 4.00 USDT and the warning shows

#### Scenario: The warning never blocks Save

- GIVEN a stored share of `10` and the field holds `1` with the warning showing
- WHEN the owner presses Save
- THEN Save was enabled and the request `{"allocation_percent": "1"}` is sent

#### Scenario: A share below 1% is allowed and warned about when it is too small

- GIVEN pool `(bybit, usdt-m, USDT)` has a balance of 300 USDT and a minimum order of 5 USDT
- WHEN the field holds `0.5`
- THEN Save is enabled and the warning shows, because the share asks for 1.50 USDT

#### Scenario: No figure, no warning

- GIVEN the pool has no balance yet
- WHEN the control renders
- THEN no warning shows

### Requirement: The Exchange's Minimum Per Pair Is Not Checked By The Panel

> **Added 2026-10-06 (owner decision 48, answered 2026-10-06 to Q5; design addendum "unit 12f" § C3). A known limit of this unit.**

The panel MUST NOT compare the share, or the amount it asks for, with any pair's
minimum order at the exchange, and MUST NOT refuse a save or show a warning on
that ground. A share MAY show no warning and still be too small for a pair whose
smallest order is large. The panel MUST say so, in the second paragraph behind the
amount's information button: "Each pair also has a minimum order at the exchange,
which depends on its price and on the account's leverage. The panel does not check
it. A signal whose order would be too small is refused and nothing is opened." /
"Cada par tiene además una orden mínima en el exchange, que depende de su precio y
del apalancamiento de la cuenta. El panel no la comprueba. Una señal cuya orden
fuera demasiado pequeña se rechaza y no se abre nada."

What stands behind that sentence is only what the change's existing requirements
state: under `DRY_RUN` the simulated exchange applies no minimum quantity and no
minimum notional ("A Dry Run Sizes A Position At 1x"), so nothing refuses a share
that is too small for a pair. This requirement adds no requirement about the
worker's refusal of a live order. That refusal is existing behaviour, recorded in
the design (§ A, U25, and § O), and is not specified by this change.

#### Scenario: A share too small for a pair passes the panel

- GIVEN pool `(bybit, usdt-m, USDT)` has a balance of 1000 USDT and a minimum order of 5 USDT, and strategy S1 allows a pair whose smallest order at the exchange would need 12 USDT of margin
- WHEN the field holds `1`, so the share asks for 10 USDT
- THEN no warning shows and Save is enabled

#### Scenario: No venue is read for the check

- GIVEN the owner moves the handle and saves
- WHEN the requests the control made are listed
- THEN none asked the exchange or a pair's contract for a minimum, and none is a request other than the strategy's save and the share preview

#### Scenario: The limit is stated behind the amount's button

- GIVEN the control renders with both information buttons closed
- WHEN the owner activates the button named "About this amount and what is not checked"
- THEN the sentence "The panel does not check it." is in the document, and before activation it was not

### Requirement: Two Information Buttons Hold The Control's Explanations

> **Added 2026-10-06 (owner decision 48, answered and approved 2026-10-06; design addendum "unit 12f" § B2).**

The explanations of the share control MUST NOT stay on screen. The control MUST
carry two information buttons, each revealing its text in place, in the flow,
directly under its own row, and never in a floating layer:

| Button | Sits | Named | Reveals |
| --- | --- | --- | --- |
| 1 | Right after the label | "About the share of the pool" / "Acerca del porcentaje del pool" | "Each new operation asks for this share of the pool's total balance. A change applies from the next operation; one already open keeps its size." |
| 2 | Right after the amount | "About this amount and what is not checked" / "Acerca de este importe y de lo que no se comprueba" | First paragraph: "An estimate: this share of the pool's total balance, read at {time} UTC. The balance is read again when an operation opens, and the pool grants less when less is free. It is margin; the position is this amount times the account's leverage." Second paragraph: the sentence of "The Exchange's Minimum Per Pair Is Not Checked By The Panel" |

What is always visible and what is behind a button:

| Line | Where |
| --- | --- |
| The label, the field with its sign, the track, the legend | Always visible |
| The amount, or its loading mark, or the em dash | Always visible |
| The stale-balance line, the "not read yet" line and the "could not be loaded" line | Always visible |
| The warning of "A Share That Asks For Less Than The Pool's Minimum Order Is Warned About And Never Blocked" | Always visible |
| The validation text, a refused save, the unreadable stored value, "Saved" (the Save button's own text) | Always visible |
| What the share is, and that a change applies from the next operation | Behind button 1 |
| That the amount is an estimate, is margin, and when the balance was read | Behind button 2 |
| That the exchange's minimum per pair is not checked | Behind button 2 |

Behaviour:

- Both buttons MUST start closed on every visit and MUST be real buttons that
  state whether their text is open or closed; Enter and Space MUST toggle them.
- Each MUST open and close its own text; both MAY be open at once.
- A button MUST close its text when activated again. Escape MUST close the text
  while focus is on the button or inside the text, and leave focus on the button.
  Focus leaving, or a press elsewhere, MUST NOT close it.
- Their state MUST survive a save and a change of language, and MUST be reset when
  another strategy's page is shown. Nothing is stored.
- They MUST NEVER be disabled: on an archived strategy and during a save,
  reading is still allowed.
- The amount's row, and so its button, MUST be present in every state of the
  amount, including the em dash.
- A closed explanation MUST be neither in the document's text nor found by a
  reader; its container MUST stay present so that the button always points at
  something.
- Except in the stale state, the time the balance was read is behind button 2,
  not on screen. Wherever the stale line or button 2's first paragraph names it,
  the time MUST be written `HH:MM UTC` (for example "14:03 UTC").

#### Scenario: Both buttons start closed and no explanation is in the document

- GIVEN strategy S1's detail view renders
- WHEN the control is read
- THEN both buttons report closed, and none of the three sentences "Each new operation asks for…", "An estimate: this share…" and "Each pair also has a minimum order…" is in the document

#### Scenario: Button 1 reveals what the share is

- GIVEN both buttons are closed
- WHEN the owner activates "About the share of the pool"
- THEN the button reports open and the sentence "Each new operation asks for this share of the pool's total balance. A change applies from the next operation; one already open keeps its size." is in the document under the label's row

#### Scenario: Button 2 reveals two paragraphs

- GIVEN pool `(bybit, usdt-m, USDT)`'s balance was read at 14:03 UTC
- WHEN the owner activates "About this amount and what is not checked"
- THEN the first paragraph "An estimate: this share of the pool's total balance, read at 14:03 UTC. …" and the second paragraph "Each pair also has a minimum order at the exchange, …" are in the document under the amount's row

#### Scenario: The buttons are independent

- GIVEN button 1 is open
- WHEN the owner activates button 2
- THEN both are open, and activating button 1 closes only its own text

#### Scenario: Escape closes the text and keeps focus on the button

- GIVEN button 2 is open and focus is inside its text
- WHEN the owner presses Escape
- THEN its text closes and focus is on button 2

#### Scenario: Focus leaving or a press elsewhere does not close it

- GIVEN button 1 is open
- WHEN the owner moves the handle, or moves focus to the field
- THEN button 1's text is still open

#### Scenario: The state survives a save and a change of language

- GIVEN button 2 is open
- WHEN the owner saves the share and then switches the language to Spanish
- THEN button 2 is still open, and its text is the Spanish one

#### Scenario: Another strategy's page starts closed

- GIVEN button 1 is open on strategy S1's page
- WHEN strategy S2's page is shown
- THEN both buttons report closed

#### Scenario: The buttons are never disabled

- GIVEN strategy S1 is archived, and in a second case a save is in flight
- WHEN the owner activates either button
- THEN it opens

#### Scenario: The amount's button stays when there is no figure

- GIVEN the field holds `abc`
- WHEN the control renders
- THEN an em dash shows, and the button "About this amount and what is not checked" is present and enabled

#### Scenario: What must be visible without a click is visible

- GIVEN a stale balance, a share asking for less than the pool's minimum order, and both buttons closed
- WHEN the control is read
- THEN the stale-balance line and the warning are both in the document

### Requirement: The Share Control Is Operable By Keyboard And Named For Assistive Technology

> **Added 2026-10-06 (owner decision 48; design addendum "unit 12f" § C).**

The tab order MUST be the order on screen: the label's information button, the
field, the track, the four stops in order, the amount's information button, Save.
Nine stops. The amount, the warning and an opened explanation take no stop.

- On the track an arrow key MUST move one step, Home MUST go to 1 and End to 100.
- The track and the field MUST both be named by the visible label. The track
  MUST expose a minimum 1, a maximum 100, a step 1 and a value text with the
  exact value, "{value}% of the pool" / "{value} % del pool", so that a stored
  `33.5` is read as "33.5% of the pool" while the handle sits at 34.
- Each stop MUST show "25%" (and so on), be named "Set the share to {value}%" /
  "Fijar el porcentaje en {value} %", and report pressed exactly when the value
  equals that stop; Enter or Space MUST activate it.
- The field MUST be marked invalid and tied to its refusal text when it holds an
  invalid value. The `%` sign MUST be hidden from assistive technology.
- The warning MUST be a status; each refusal of a save MUST be an alert.
- Each information button MUST keep one name whatever its state.
- Hit areas: the track MUST be 44 px tall; each stop and each information button
  MUST be at least 44 by 44 px; the field and Save MUST be at least 44 px tall.
- Every control MUST show the panel's focus ring when focused.

#### Scenario: Tab visits nine stops in the order on screen

- GIVEN the control is on screen on an unarchived strategy with a valid value that changed, so Save is enabled (a disabled Save is not a tab stop)
- WHEN the owner presses Tab from before the control
- THEN focus visits, in order: the button "About the share of the pool", the field, the track, "25%", "50%", "75%", "100%", the button "About this amount and what is not checked", and Save
- AND with Save disabled (nothing changed) the order ends at the button "About this amount and what is not checked"

#### Scenario: Arrow, Home and End on the track

- GIVEN the track is focused at step 34
- WHEN the owner presses the right arrow, then Home, then End
- THEN the value is 35, then 1, then 100

#### Scenario: The track reads the exact value

- GIVEN a stored share of `33.5`
- WHEN the track's accessible state is read
- THEN its minimum is 1, its maximum is 100, its step is 1, its value text is "33.5% of the pool", and its name is "Share of the pool per trade"

#### Scenario: A stop says what it does and whether it is the value

- GIVEN the value is exactly `50`
- WHEN the stops are read
- THEN the stop named "Set the share to 50%" reports pressed and the other three do not

#### Scenario: The invalid field is described

- GIVEN the field holds `abc`
- WHEN the field's accessible state is read
- THEN it is invalid and described by "Enter a number, for example 25 or 33.5."

#### Scenario: Hit areas are at least 44 px

- GIVEN the control is on screen
- WHEN the stops, the information buttons, the field, the track and Save are measured by their classes
- THEN each stop and each information button is at least 44 by 44 px, the track is 44 px tall, and the field and Save are at least 44 px tall

### Requirement: A Save Of The Share Or Of The Allowed Pairs Shows "Saved"

> **Added 2026-10-06 (owner decisions 44 (12f.4) and 48, answered 2026-10-06; design addendum "unit 12f" § D).** "Saved" / "Guardado" are the owner's own words.
>
> **Changed 2026-10-10 (owner decision 52, task 12f.10.30d).** "Saved" is the text of the Save button itself, no longer a text beside it. When it shows and when it goes are unchanged.

After a save of the share and after a save of the allowed pairs, the control's
Save button MUST read "Saved" / "Guardado" in place of "Save share" / "Save pairs"
(its accessible name is the text it shows), and MUST be disabled while it does.
While a save is in flight it MUST still read "Saving…" / "Guardando…". No visible
"Saved" MUST stand beside the button. The button MUST have ONE width for all of
its texts, the width of its longest in the current language, so the change of
text moves nothing around it: every text it can show sits in one cell, and the
ones not shown MUST be hidden from sight and from assistive technology. Because a
change of a button's text is not announced, the control MUST keep a visually
hidden polite status region that says "Saved" / "Guardado" in the same states: it
MUST be in the document before it has anything to say, empty until then. There
MUST be NO timer: it stays until the owner changes something in that control
again.

| Control | "Saved" appears | "Saved" goes |
| --- | --- | --- |
| The share | When the PATCH answers 200 with a strategy | At the next movement of the handle, activation of a stop, or keystroke in the field; and when the page is left |
| The allowed pairs | When the PUT answers 200 and the list on screen is the saved one | At the next pair added or removed; and when the page is left. Typing in the search box changes no pair and leaves it. |

A failed save MUST show its refusal and NEVER "Saved"; the two MUST NEVER be on
screen together: a button that reads "Saved" is disabled, so a save is sent only
after a change, and the change has already cleared "Saved". If the re-read of the
allowed pairs after a 200 fails, so that the list on screen is the old one,
"Saved" MUST NOT be shown.

#### Scenario: "Saved" shows after the share is saved

- GIVEN the owner saved a share of `33.5` and the API answered 200 with a strategy
- WHEN the control is read
- THEN the Save button reads "Saved" and is disabled, "Save share" is not its name, and no visible "Saved" stands beside it

#### Scenario: "Saved" goes at the next change of the share

- GIVEN "Saved" shows after a share save
- WHEN the owner moves the handle, activates a stop, or types a character, each tried in turn
- THEN the button reads "Save share" again and "Saved" is gone each time

#### Scenario: "Saved" stays until something changes

- GIVEN "Saved" shows after a share save
- WHEN ten minutes pass with no change
- THEN the button still reads "Saved"

#### Scenario: "Saved" shows after the allowed pairs are saved

- GIVEN strategy S1 on pool `(bybit, usdt-m, USDT)` had allowed pairs `{ETHUSDT}`, the owner added `SOLUSDT` and the PUT answered 200
- WHEN the pairs control is read
- THEN the Save pairs button reads "Saved" and is disabled, and goes back to "Save pairs" when a pair is added or removed again

#### Scenario: Typing in the pair search does not remove "Saved"

- GIVEN "Saved" shows after a pairs save
- WHEN the owner types `SOL` in the pair search box without adding or removing a pair
- THEN the button still reads "Saved"

#### Scenario: A refused save never shows "Saved"

- GIVEN the owner saved a share and the API answered 409, or 500
- WHEN the control is read
- THEN the refusal shows and "Saved" does not

#### Scenario: A new save, after a change, shows no "Saved" while it is in flight

- GIVEN "Saved" shows after a share save, and the owner changes the value and presses Save again
- WHEN the second request is in flight
- THEN the button reads "Saving…" and "Saved" is not shown

#### Scenario: A button that reads "Saved" cannot save again

- GIVEN "Saved" shows after a share save
- WHEN the owner presses the button
- THEN nothing is sent, because the button is disabled

#### Scenario: The button has one width for all of its texts

- GIVEN a Save button
- WHEN the document is read
- THEN the button holds "Save share", "Saving…" and "Saved" in one cell, the one shown is its accessible name, and the other two are hidden from sight and from assistive technology

#### Scenario: The live region exists before it speaks

- GIVEN the share control and the pairs control render with nothing saved
- WHEN the document is read
- THEN each has a polite status region that is empty and visually hidden, and that says "Saved" when the button reads it

#### Scenario: A failed re-read after a successful pairs save shows no "Saved"

- GIVEN the PUT of the allowed pairs answered 200 and the re-read of the list then fails, so the old list is on screen
- WHEN the pairs control is read
- THEN "Saved" does not show

### Requirement: The Webhook Block Has Two Copy Buttons

> **Added 2026-10-06 (owner decisions 44 (12f.5) and 48, answered 2026-10-06; design addendum "unit 12f" § E).** "Copied" / "Copiado" are the owner's own words.

The webhook block MUST offer two buttons: "Copy URL" / "Copiar URL" beside "Show
secret", and "Copy message" / "Copiar mensaje" under the alert message. "Copy
message" MUST write the message shown. "Copy URL" MUST write the URL that works in
TradingView, with the webhook's host and the real secret, percent-encoded, whether
the secret is shown or hidden: with the secret shown, the URL on screen, copied as
it is with no request; with the secret hidden, the URL built from the secret that
the click asks the server for (`GET /api/webhook-secret`), while the screen keeps
the placeholder and nothing is revealed. The panel MUST NEVER write the placeholder
URL to the clipboard. The secret of a hidden copy MUST be a local value of that one
click: it MUST NOT be kept in component state, in the query cache, in a log, in an
error text, in an attribute or in a hidden element, and a later "Show secret" MUST
make its own request. The panel MUST NOT claim to clear the clipboard when the
secret is hidden or the view is left. The URL MUST be text, never a link, and MUST
NEVER be requested.

> **Changed 2026-10-10 (owner decision 52, task 12f.10.30d).** "Copied" is the text of the Copy button itself, no longer a text beside it. When it shows and when it goes are unchanged.

> **Changed 2026-10-10 (owner decision 53, task 12f.10.30e).** "Copy URL" copies the URL that works even while the secret is hidden, where it copied the text on screen, the placeholder, which does not work in TradingView. With no host it is disabled. Showing or hiding the secret no longer removes "Copied", because the clipboard holds the same URL either way.

After a copy the panel MUST show:

| Result | Text of the button activated | Until |
| --- | --- | --- |
| The alert message was copied | The button reads "Copied" / "Copiado" | Something else is copied, or the block is closed |
| The URL was copied | The button reads "Copied" / "Copiado" | The same, AND the host on screen stops being the one that was copied |
| The request for the secret failed, or the browser refused, or has no clipboard | The button keeps its ordinary text, nothing is written to the clipboard by a failed request, and "Could not copy. Select the text and copy it by hand." / "No se pudo copiar. Seleccione el texto y cópielo a mano." shows beside it in the loss colour | As the row of the button it belongs to |

While the request for the secret of a hidden copy is in flight, "Copy URL" MUST be
disabled and keep its text, so a second click sends no second request. With no
host ("No public host is configured", "could not be loaded" or still loading),
"Copy URL" MUST be disabled and write nothing, because the path alone does not
work in TradingView; with a host it is enabled. A button that reads "Copied" and
is not disabled MUST stay enabled and MUST copy again when pressed.
No visible "Copied" MUST stand beside a button. Each Copy button MUST have ONE
width for both of its texts, the width of its longest in the current language,
so the change of text moves nothing: both texts sit in one cell, and the one not
shown MUST be hidden from sight and from assistive technology, which makes the
text shown the button's accessible name. Because a change of a button's text is
not announced, each Copy button MUST keep a visually hidden polite status region,
in the document from the first render, that says "Copied" / "Copiado" in the same
states; a refusal is said in the same region, visibly.

"Copied" on the URL's button MUST be shown only while the host on screen is the
one copied. Showing or hiding the secret MUST NOT remove it, because the clipboard
holds the same working URL either way; a host read that answers with a different
host after the copy MUST remove it. It also goes when the other button is used.
The message's "Copied" MUST NOT be touched by showing or hiding the secret. Only
one "Copied" MUST be on screen: a copy with the other button moves it. The panel
MUST NOT keep the copied text; it MAY keep only which button was used, whether it
worked and the host it was made with.

#### Scenario: Copying the URL with the secret hidden copies the URL that works

- GIVEN strategy S1's webhook block is open, the secret is hidden, the webhook's host is `https://example.duckdns.org` and the server's secret is `p&q/r s`
- WHEN the owner activates "Copy URL"
- THEN the clipboard holds exactly `https://example.duckdns.org/webhook/tradingview?secret=p%26q%2Fr%20s`, the button reads "Copied", one request for the secret was made, the URL on screen still shows the placeholder, "Show secret" still reads "Show secret", and the secret is in no text, attribute or query-cache entry of the page

#### Scenario: Copying the URL with the secret revealed copies the real URL

- GIVEN the owner pressed "Show secret" and the real URL is on screen
- WHEN the owner activates "Copy URL"
- THEN the clipboard holds exactly the URL on screen, the button reads "Copied", and no request for the secret was made by the copy

#### Scenario: A hidden copy leaves the secret in no cache

- GIVEN the owner copied the URL with the secret hidden
- WHEN the query cache is read, and the owner then presses "Show secret"
- THEN the cache held no secret after the copy, and "Show secret" made its own request

#### Scenario: A failed request writes nothing and says so

- GIVEN the secret is hidden and `GET /api/webhook-secret` fails (network, 401, 5xx, or a body that is not a secret)
- WHEN the owner activates "Copy URL"
- THEN nothing is written to the clipboard, "Could not copy. Select the text and copy it by hand." shows beside the button, the button keeps reading "Copy URL", and the placeholder URL was not written

#### Scenario: A click while the request is in flight sends no second request

- GIVEN the owner activated "Copy URL" with the secret hidden and the request has not answered
- WHEN the owner clicks the button again
- THEN the button is disabled with the same text and no second request is sent

#### Scenario: With no host, "Copy URL" is disabled

- GIVEN the webhook's host is not configured, could not be loaded, or is still loading
- WHEN the webhook block is open
- THEN "Copy URL" is disabled and writes nothing, "Copy message" is enabled, and the sentence that says why there is no host is unchanged

#### Scenario: Showing or hiding the secret leaves "Copied" on the URL's button

- GIVEN the owner copied the URL, with the secret hidden or revealed, and the button reads "Copied"
- WHEN the owner presses "Show secret" and then "Hide secret"
- THEN the button still reads "Copied"

#### Scenario: A different host after the copy removes "Copied"

- GIVEN the owner copied the URL and the button reads "Copied"
- WHEN the host read answers with a different host and the URL on screen changes
- THEN the button reads "Copy URL" again

#### Scenario: The message's "Copied" survives showing and hiding the secret

- GIVEN the owner copied the alert message and "Copy message" reads "Copied"
- WHEN the owner presses "Show secret" and then "Hide secret"
- THEN "Copy message" still reads "Copied"

#### Scenario: A copy with the other button moves "Copied"

- GIVEN "Copy message" reads "Copied"
- WHEN the owner activates "Copy URL"
- THEN "Copy URL" reads "Copied" and "Copy message" reads "Copy message" again, so only one button reads "Copied"

#### Scenario: A button that reads "Copied" copies again

- GIVEN "Copy URL" reads "Copied"
- WHEN the owner presses it
- THEN it copies the working URL again, asking again for the secret if it is hidden, and still reads "Copied"

#### Scenario: A refused copy says so and never reads "Copied"

- GIVEN the browser refuses the clipboard write
- WHEN the owner activates "Copy URL"
- THEN "Could not copy. Select the text and copy it by hand." shows beside the button in the loss colour, the button keeps reading "Copy URL", no button reads "Copied", and nothing is written to the console

#### Scenario: A browser with no clipboard says so

- GIVEN the panel is opened where no clipboard is available
- WHEN the owner activates "Copy message"
- THEN "Could not copy. Select the text and copy it by hand." shows

#### Scenario: Only "Show secret" and a hidden "Copy URL" request the secret

- GIVEN the secret is hidden and the webhook's host is set
- WHEN the owner activates "Copy message" and every other control of the view and the requests are counted
- THEN no request to `GET /api/webhook-secret` was made; and "Copy URL" then makes exactly one, and "Show secret" one more

#### Scenario: The URL is never a link and never requested

- GIVEN the webhook block shows the URL with a host
- WHEN the document is read and the requests the page made are listed
- THEN the URL is not inside a link, and no request starts with the webhook's host

### Requirement: The Webhook URL Is Shown And Copied With Its Host

> **Added 2026-10-06 (owner decisions 44 (12f.6), 5 and 48; design addendum "unit 12f" § F).**

The webhook block MUST show the full URL TradingView posts to: the webhook's
origin, then `/webhook/tradingview?secret=`, then the placeholder or, once
revealed, the secret. The origin MUST come from the backend, by
`GET /api/webhook-origin`, read when the block is opened, and MUST NEVER be
compiled into the panel's bundle: the webhook is not on the panel's origin
(decision 5). The panel MUST use the answer only when it is a serialised origin
(scheme, host and optional port, with no path, query, fragment, user, trailing
slash or upper case); anything else MUST be treated as no host. The origin MUST
be displayed and copied, MUST NEVER be fetched, and MUST NOT be a link or a form
target.

- While the host is loading, the path alone MUST be shown, and "Copy URL" MUST
  be disabled (decision 53: the path alone does not work in TradingView).
- When the answer is `{"origin": null}`: the path alone and "No public host is
  configured for the webhook, so only the path is shown. Put your webhook's host
  in front of it." / "No hay un host público configurado para el webhook, por lo
  que solo se muestra la ruta. Anteponga el host de su webhook."
- When the read fails (any failure, including a 404 from an older API) or the
  answer is not accepted: the path alone and "The webhook's host could not be
  loaded, so only the path is shown." / "No se pudo cargar el host del webhook,
  por lo que solo se muestra la ruta."

#### Scenario: A configured host is shown in the URL

- GIVEN `GET /api/webhook-origin` answers `{"origin": "https://example.duckdns.org"}` and the secret is hidden
- WHEN the webhook block is opened
- THEN the URL on screen is `https://example.duckdns.org/webhook/tradingview?secret=` followed by the placeholder, with no sentence about a missing host

#### Scenario: A revealed secret goes after the host

- GIVEN the same origin and the owner pressed "Show secret"
- WHEN the URL renders
- THEN it is `https://example.duckdns.org/webhook/tradingview?secret=` followed by the percent-encoded secret

#### Scenario: No configured host shows the path and says why

- GIVEN `GET /api/webhook-origin` answers `{"origin": null}`
- WHEN the webhook block is opened
- THEN the URL on screen is the path `/webhook/tradingview?secret=` and the placeholder, and "No public host is configured for the webhook, so only the path is shown. Put your webhook's host in front of it." shows

#### Scenario: A failed read shows the path and says it could not be loaded

- GIVEN `GET /api/webhook-origin` answers 404, as an older API does
- WHEN the webhook block is opened
- THEN the path alone shows and "The webhook's host could not be loaded, so only the path is shown." shows

#### Scenario: An origin the panel does not accept is treated as no host

- GIVEN `GET /api/webhook-origin` answers `{"origin": "https://example.duckdns.org/"}`
- WHEN the webhook block is opened
- THEN the path alone shows and "The webhook's host could not be loaded, so only the path is shown." shows

#### Scenario: The host loading shows the path alone

- GIVEN `GET /api/webhook-origin` has not answered
- WHEN the webhook block is opened
- THEN the path alone shows, and "Copy URL" is disabled at that moment

#### Scenario: The host is never compiled in

- GIVEN the panel's built bundle
- WHEN it is searched for the DuckDNS host of the deployment
- THEN the host is not in it

#### Scenario: The only request added is to the panel's own API

- GIVEN the webhook block is opened with a host
- WHEN the requests the page made are listed
- THEN the one added is `GET /api/webhook-origin`, and none goes to the webhook's host

### Requirement: By Pair Shows A Win Rate

> **Added 2026-10-06 (owner decision 44, answered 2026-10-06 twice; design addendum "unit 12f" § G and § N Q4).**

The "By pair" table of the strategy detail view MUST have these columns, in this
order: Pair, Trades, Win rate, PnL, Return. The Win rate heading MUST read "Win
rate" / "% acierto". The mockup's OPEN column MUST NOT be built. The win rate MUST
be written as an unsigned percentage with ONE decimal ("60.0%", "58.3%"), in
neutral ink, from the ratio the API served; the panel MUST NOT divide or compute
it. The percentage MUST be CUT (truncated toward zero) at one decimal, never
rounded, so that only a pair whose every closed operation is a win reads
"100.0%"; a pair with one win in several thousand reading "0.0%" is accepted.
The server answers `wins`, `trades` and the ratio, and the panel MUST refuse a
row whose `win_rate` is not `wins` over `trades` at the ratio's own scale. No column MUST be hidden, and the table MUST scroll sideways inside its own
wrapper when it does not fit.

The panel MUST check each pair row: `wins` an integer from 0 to `trades` and
`win_rate` a string, then `win_rate` between 0 and 1, `wins` equal to 0 exactly
when the rate is 0, and equal to `trades` exactly when the rate is 1. A row that
fails MUST show the table's existing could-not-be-read state, and a figure that
was not served MUST NEVER be drawn. A `by_pair` entry without `wins` or `win_rate`
MUST be refused, which refuses the whole strategy report: against an API that does
not serve them, the strategy's performance block shows its error with "Try again"
and each row of the Strategies list shows its figures as unreadable. An older panel
MUST keep working against an API that serves them.

#### Scenario: The column sits after Trades

- GIVEN strategy S1 on pool `(bybit, usdt-m, USDT)` has closed trades on `SOLUSDT`
- WHEN the "By pair" table renders
- THEN its headings read, in order, Pair, Trades, Win rate, PnL, Return

#### Scenario: A rate is written with one decimal

- GIVEN the API serves for `SOLUSDT` `trades` 12, `wins` 7 and `win_rate` `0.5833333333`
- WHEN the table renders
- THEN the Win rate cell reads "58.3%"

#### Scenario: Three wins in five read 60.0%

- GIVEN the API serves `trades` 5, `wins` 3 and `win_rate` `0.6000000000`
- WHEN the table renders
- THEN the cell reads "60.0%"

#### Scenario: 199 wins in 200 are not written as a perfect record

- GIVEN the API serves `trades` 200, `wins` 199 and `win_rate` `0.9950000000`
- WHEN the table renders
- THEN the cell reads "99.5%", not "100%"

#### Scenario: The rate is cut, so 1,999 of 2,000 is not 100.0%

- GIVEN the API serves `trades` 2000, `wins` 1999 and `win_rate` `0.9995000000`
- WHEN the table renders
- THEN the cell reads "99.9%", not "100.0%"

#### Scenario: 2,000 of 2,000 reads 100.0%

- GIVEN the API serves `trades` 2000, `wins` 2000 and `win_rate` `1.0000000000`
- WHEN the table renders
- THEN the cell reads "100.0%"

#### Scenario: One win in 5,000 reads 0.0%

- GIVEN the API serves `trades` 5000, `wins` 1 and `win_rate` `0.0002000000`
- WHEN the table renders
- THEN the cell reads "0.0%"

#### Scenario: A ratio that does not match wins over trades is not drawn

- GIVEN the API serves `trades` 5, `wins` 3 and `win_rate` `0.7000000000`
- WHEN the table renders
- THEN no row is drawn and the table's could-not-be-read state shows

#### Scenario: Every trade won reads 100.0%

- GIVEN the API serves `trades` 4, `wins` 4 and `win_rate` `1.0000000000`
- WHEN the table renders
- THEN the cell reads "100.0%"

#### Scenario: No win reads 0.0%

- GIVEN the API serves `trades` 3, `wins` 0 and `win_rate` `0.0000000000`
- WHEN the table renders
- THEN the cell reads "0.0%"

#### Scenario: A row whose fields contradict is not drawn

- GIVEN the API serves `trades` 5, `wins` 5 and `win_rate` `0.6000000000`
- WHEN the table renders
- THEN no row is drawn and the table's could-not-be-read state shows

#### Scenario: A win rate out of range is not drawn

- GIVEN the API serves `win_rate` `1.2000000000`
- WHEN the table renders
- THEN no row is drawn and the could-not-be-read state shows

#### Scenario: A pair row without the new fields is refused

- GIVEN the panel reads an API answer whose `by_pair` entry carries `pair`, `trades`, `pnl` and `return` and neither `wins` nor `win_rate`
- WHEN the strategy's performance block renders
- THEN it shows its error with "Try again", and the Strategies list row of that strategy shows its figures as unreadable

#### Scenario: An older panel keeps working against the newer API

- GIVEN a panel build that does not know `wins` and `win_rate`, and an API that serves them
- WHEN the "By pair" table renders
- THEN it shows what it showed before and no error

#### Scenario: The table scrolls inside its wrapper

- GIVEN a viewport narrower than the five columns need
- WHEN the "By pair" table renders
- THEN all five columns are present and the table scrolls sideways inside its own wrapper

### Requirement: The Unit Adds No Browser Money Computation, No Inline Style And No Relaxed Policy

> **Added 2026-10-06 (owner decisions 44 and 48; design addendum "unit 12f" § B and § H).**

No money figure of this unit (the amount a share asks for, a pool's minimum, an
amount in a warning) MUST be computed in the browser; each MUST be the text the
server served, cut to the currency's decimals. The share control, the
information buttons and the Copy buttons MUST NOT write a style attribute or set
a style property on any element: every position that depends on a value MUST be
drawn by geometry attributes of a graphic or by fixed classes. The panel's
Content-Security-Policy MUST NOT be relaxed: no directive is widened for this
unit, and in particular `style-src` MUST NOT gain `'unsafe-inline'` and
`connect-src` MUST NOT gain any origin. All amounts of this unit are in one
pool's own settlement currency and are never summed or converted across pools.

#### Scenario: No source of the panel writes an inline style

- GIVEN the panel's non-test source files
- WHEN they are searched for an inline style attribute or property
- THEN none is found

#### Scenario: The policy is not relaxed

- GIVEN the built panel is served with its dist directory configured
- WHEN `index.html` is requested
- THEN its Content-Security-Policy carries the same directives as before this unit, `style-src` without `'unsafe-inline'`, and `connect-src` without the webhook's host

#### Scenario: Two pools are never summed

- GIVEN strategies S1 on `(bybit, usdt-m, USDT)` and S2 on `(binance, usdt-m, USDT)` each show an amount
- WHEN both pages are read
- THEN each amount is in its own pool's currency and no combined figure is shown

### Requirement: The Detail Page's Follow-Up Texts Are Exactly These, In English And Spanish

> **Added 2026-10-06 (owner decisions 44 and 48; design addendum "unit 12f" § I).** "Saved" / "Guardado" and "Copied" / "Copiado" are the owner's own words; every other line is the design's.

Every text this unit shows MUST be resolved through the panel's i18n and MUST read
exactly as below (a `{{…}}` is a value filled in):

| Text | English | Spanish |
| --- | --- | --- |
| Share label | Share of the pool per trade | Porcentaje del pool por operación |
| Button 1's name | About the share of the pool | Acerca del porcentaje del pool |
| Behind button 1 | Each new operation asks for this share of the pool's total balance. A change applies from the next operation; one already open keeps its size. | Cada nueva operación pide este porcentaje del saldo total del pool. Un cambio se aplica desde la próxima operación; una ya abierta mantiene su tamaño. |
| Button 2's name | About this amount and what is not checked | Acerca de este importe y de lo que no se comprueba |
| The amount | Asks for about {{amount}} {{currency}} per operation | Pide alrededor de {{amount}} {{currency}} por operación |
| Behind button 2, first paragraph | An estimate: this share of the pool's total balance, read at {{time}} UTC. The balance is read again when an operation opens, and the pool grants less when less is free. It is margin; the position is this amount times the account's leverage. | Es una estimación: este porcentaje del saldo total del pool, leído a las {{time}} UTC. El saldo se vuelve a leer cuando se abre una operación, y el pool concede menos cuando hay menos disponible. Es margen; la posición es este importe por el apalancamiento de la cuenta. |
| Stale balance | The pool's balance was last read at {{time}} UTC and may be out of date. | El saldo del pool se leyó por última vez a las {{time}} UTC y puede estar desactualizado. |
| No balance | The pool's balance has not been read yet, so the amount cannot be shown. | El saldo del pool todavía no se ha leído, por lo que no se puede mostrar el importe. |
| Loading | Calculating the amount… | Calculando el importe… |
| Amount failed | The amount could not be loaded. | No se pudo cargar el importe. |
| Below the pool's minimum | At this balance the share asks for less than the pool's minimum order, {{minimum}} {{currency}}. Openings would be skipped until the share or the balance is larger. | Con este saldo, el porcentaje pide menos que la orden mínima del pool, {{minimum}} {{currency}}. Las aperturas se omitirían hasta que el porcentaje o el saldo sean mayores. |
| Behind button 2, second paragraph | Each pair also has a minimum order at the exchange, which depends on its price and on the account's leverage. The panel does not check it. A signal whose order would be too small is refused and nothing is opened. | Cada par tiene además una orden mínima en el exchange, que depende de su precio y del apalancamiento de la cuenta. El panel no la comprueba. Una señal cuya orden fuera demasiado pequeña se rechaza y no se abre nada. |
| The track's value text | {{value}}% of the pool | {{value}} % del pool |
| A stop's name | Set the share to {{value}}% | Fijar el porcentaje en {{value}} % |
| Not a number | Enter a number, for example 25 or 33.5. | Escriba un número, por ejemplo 25 o 33,5. |
| Out of range | The share must be above 0 and at most 100. | El porcentaje debe ser mayor que 0 y como máximo 100. |
| Save | Save share | Guardar porcentaje |
| Saving | Saving… | Guardando… |
| Save failed | The share was not saved. Try again. | El porcentaje no se guardó. Inténtelo de nuevo. |
| Archived | This strategy is archived and can no longer be changed. | Esta estrategia está archivada y ya no se puede modificar. |
| Gone | This strategy no longer exists. | Esta estrategia ya no existe. |
| Unreadable | The stored share could not be read, so it cannot be edited here. | No se pudo leer el porcentaje guardado, por lo que no se puede editar aquí. |
| Saved | Saved | Guardado |
| Copy URL | Copy URL | Copiar URL |
| Copy message | Copy message | Copiar mensaje |
| Copied | Copied | Copiado |
| Copy failed | Could not copy. Select the text and copy it by hand. | No se pudo copiar. Seleccione el texto y cópielo a mano. |
| No host configured | No public host is configured for the webhook, so only the path is shown. Put your webhook's host in front of it. | No hay un host público configurado para el webhook, por lo que solo se muestra la ruta. Anteponga el host de su webhook. |
| Host failed | The webhook's host could not be loaded, so only the path is shown. | No se pudo cargar el host del webhook, por lo que solo se muestra la ruta. |
| Win rate heading | Win rate | % acierto |

#### Scenario: Every text reads exactly in English

- GIVEN the locale is English and each state of this unit's controls is brought on screen
- WHEN each text is read
- THEN it equals the English column above

#### Scenario: Every text reads exactly in Spanish

- GIVEN the locale is Spanish and each state of this unit's controls is brought on screen
- WHEN each text is read
- THEN it equals the Spanish column above, and no English text is left

#### Scenario: The owner's own words are unchanged

- GIVEN either locale
- WHEN the confirmation after a save and after a copy is read
- THEN they read "Saved" / "Guardado" and "Copied" / "Copiado"

### Requirement: Settings Reads Two Existing Routes And Changes No API

> **Replaces 2026-10-10 (owner decisions 18, 20, 22, 54, 58).** September's
> "Settings Manages One Key Per Exchange" is withdrawn.

The Settings view MUST read `GET /api/credentials` and `GET /api/pools`, and
MUST write only through the existing `PUT /api/credentials/{exchange}` (save)
and `DELETE /api/credentials/{exchange}` (delete). Settings MUST add no route,
no response field, no status and no migration. `ApiError` MAY gain one
read-only field, `responseBody`, holding the RESPONSE's JSON body when it is an
object; it MUST NOT hold anything of the request, and every field it already
has MUST keep its meaning.

The panel MUST keep one small file of the exchanges whose key it manages
(`frontend/src/shared/credentials/served-exchanges.json`): their ids in display
order, and for each the confirmations its form asks for (none for Bybit;
`withdrawals_disabled_confirmed` and `futures_enabled_confirmed` for Binance).
That file MUST equal the server's tables, as "The Panel's List Of Served
Exchanges Equals The Server's Tables" in the exchange-credentials capability
requires; that requirement is a test and changes no behaviour.

#### Scenario: The panel reads the two routes and writes through the two

- GIVEN the owner opens Settings, saves a key and deletes a key
- WHEN the requests the panel sent are listed
- THEN the reads are `GET /api/credentials` and `GET /api/pools`, and the writes are one `PUT` and one `DELETE` to `/api/credentials/{exchange}`, with no other write

#### Scenario: The error keeps the response body and never the request body

- GIVEN a `PUT` whose body holds a sentinel string is answered 422, then 500, then fails with no answer
- WHEN the thrown `ApiError` is inspected
- THEN no own property of it and not its `message` holds the sentinel, and for a 409 whose body carries top-level lists `responseBody` holds them
- AND `status`, `outcome`, `detail`, `code` and `fields` keep the values they had before the field existed

#### Scenario: The served list is not a change of the API

- GIVEN the change is applied
- WHEN the backend's production files are compared with those before it
- THEN no router, schema, model or migration differs because of Settings

### Requirement: Every Exchange The Panel Knows Has A Card In Exactly One State

> **Replaces 2026-10-10 (owner decisions 20, 22, 54, 58).**

Settings MUST show one card per exchange, an `<article>` named by its `h3`, the
exchange's proper name (`Bybit`, `Binance`, `Pionex`; an id with no entry is
shown as the API spells it). The exchanges listed MUST be the union, without
repeats, of: the served exchanges in the file's order; then every other
exchange in `GET /api/credentials`; then every other exchange that has a pool
in `GET /api/pools`, the last two sorted by name. So every tab has a card, a
stored key is always shown, and an exchange with no row in either route (Binance
before its first key) still has a card.

One pure function (`keyState`) MUST give each exchange its state from three
inputs, and the card and the tab MUST both draw from it. An entry that is
`EMPTY` and an exchange not listed mean the same: no active key. `poolOn` is
true when at least one pool of the exchange has `enabled: true`, and is unknown
while the pools are loading or failed.

| Active key | `trade_capable` | `poolOn` | State | Mark (card and tab) |
| --- | --- | --- | --- | --- |
| stored | true | any | key | none |
| stored | false | any | read-only | `read-only`, amber |
| none | - | true | degraded | `no key`, amber |
| none | - | false | empty (never had a key, or it was deleted) | `no key`, neutral |
| none | - | unknown | empty, with the page's notice that the pools could not be loaded | `no key`, neutral |

Whether an exchange is served MUST be a second axis, not a state: it decides
only whether the card has buttons.

The card MUST say, in these exact English words with `{x}` the exchange's name:

| State | Sentence | Buttons |
| --- | --- | --- |
| key | none | Replace key, Delete key |
| read-only | "This key cannot trade. With dry run off, opening signals for {x} are refused until you add a key that can trade futures." | Replace key, Delete key |
| degraded | "No key stored. With dry run off, opening signals for {x} are refused until a key is added." | Add key |
| empty | "No key stored. Add one to read and trade on {x} from here." | Add key |

An empty or degraded card's key line MUST hold the `no key` tag and nothing else.

#### Scenario: A key that trades is neutral and unmarked

- GIVEN Bybit has an active key with `trade_capable` true
- WHEN Settings renders
- THEN Bybit's card has no mark and no sentence, and offers "Replace key" and "Delete key"

#### Scenario: A read-only key is marked and explained

- GIVEN Bybit's active key has `trade_capable` false
- WHEN Settings renders
- THEN the card shows the amber `read-only` tag and the read-only sentence, and offers "Replace key" and "Delete key"

#### Scenario: A degraded exchange is marked and explained

- GIVEN Binance has no active key and an enabled pool
- WHEN Settings renders
- THEN the card shows the amber `no key` tag, the degraded sentence and "Add key"

#### Scenario: An exchange that never had a key, or whose key was deleted, is empty and neutral

- GIVEN Binance has no active key and no enabled pool
- WHEN Settings renders
- THEN the card shows the grey `no key` tag, the empty sentence and "Add key", no key hint and no facts, and nothing on it is amber

#### Scenario: Binance with no row in either route still has a card

- GIVEN neither `GET /api/credentials` nor `GET /api/pools` lists Binance
- WHEN Settings renders
- THEN a Binance card exists, in the empty state, after the Bybit card, and offers "Add key"

#### Scenario: A stored key of an exchange nothing else lists is shown

- GIVEN `GET /api/credentials` lists a stored key for an exchange that is not in the served file and has no pool
- WHEN Settings renders
- THEN that exchange has a card showing the key, after the served cards

#### Scenario: Unknown pools do not call an exchange degraded

- GIVEN `GET /api/pools` failed and Binance has no active key
- WHEN Settings renders
- THEN Binance's card is in the empty state with a grey `no key`, no card is amber for lack of a key, and one line says that the pools could not be loaded so an exchange without a key is not marked

#### Scenario: A row that is not believed is an error, not "no keys"

- GIVEN `GET /api/credentials` answers a stored row whose `last4` is not exactly four characters, or a body that is not a list of valid rows
- WHEN Settings renders
- THEN the keys are treated as failed to load, the bad `last4` is drawn nowhere, and no card says "No key stored"

### Requirement: Settings States Its Own Loading And Failure

> **Added 2026-10-10 (design addendum, section B).**

While `GET /api/credentials` has no data, Settings MUST show "Loading exchange
keys…" and no card. When it failed with no data, Settings MUST show "Exchange
keys could not be loaded." and "Try again" and MUST NOT show a card, because a
card drawn from the served file alone would say "No key stored" about a key the
panel could not read. When it has data and a later read failed, the cards MUST
stay under the line "This list could not be refreshed and may be out of date."
with "Try again".

#### Scenario: Loading shows no card

- GIVEN the credentials read has not answered
- WHEN Settings renders
- THEN "Loading exchange keys…" is shown and no card is

#### Scenario: A failed first read shows no card

- GIVEN the credentials read failed and nothing was read before
- WHEN Settings renders
- THEN "Exchange keys could not be loaded." and "Try again" are shown, no card is, and "Try again" reads the list again

#### Scenario: A failed later read keeps the cards

- GIVEN the credentials were read and a later read failed
- WHEN Settings renders
- THEN the cards stay, the line "This list could not be refreshed and may be out of date." and "Try again" are shown

### Requirement: A Stored Key's Card Shows The Key Hint And Its Facts As Tags

> **Replaces 2026-10-10 (owner decision 55).**

A card with a stored key MUST show, as the head's second line, the key hint
and, beside it, a date. The key hint MUST be a paragraph (not a heading) in the
largest text of the card, the label `key`, four dots and the last four
characters of the key, with only those characters in the strongest ink. It
MUST never hold more than the last four characters: not in text, not in an
attribute, not in a hidden label, not in a test fixture. The label, the dots and
the characters MUST be hidden from assistive technology and a hidden text MUST
say "key ending in {last4}". The date MUST read "checked {date}" (a UTC day in
the panel's language) when `validated_at` is set and "not validated" when it is
null; it MUST NOT be among the tags. The hint and the date MUST each be
unbreakable, so that when both do not fit the date moves under the hint whole.

The facts MUST be one list of tags, named "What is known about this key". Each
fact MUST be one `<li>` that cannot break inside, the list MUST wrap whole tags
onto a new line when the width runs out, and the card MUST hold no separator
character between facts. Each of trade and withdrawal MUST be said by exactly
one tag. The tags, in this order:

| # | Fact | Condition | EN tag | ES tag | Look |
| --- | --- | --- | --- | --- | --- |
| 1 | the mark | state read-only | `read-only` | `solo lectura` | mark, amber |
| 2 | capability | trade source `VERIFIED` and `trade_capable` true | `trades` | `opera` | checked |
| | | trade source `VERIFIED` and `trade_capable` false | no tag | | |
| | | trade source not `VERIFIED` and `validated_at` set | `reads` | `lee` | checked |
| | | `validated_at` null | no tag | | |
| 3 | withdrawal | withdraw source `VERIFIED` | `no withdrawal` | `sin retiros` | checked |
| 4 | transfers | `internal_transfer` true | `transfers` | `transfiere` | checked |
| | | `internal_transfer` false | `no transfers` | `sin transferencias` | checked |
| | | null | no tag | | |
| 5 | trade, not checked by the venue | source `OWNER_CONFIRMED` and `trade_confirmed_at` set | `trade confirmed {date}` | `operar: confirmado el {date}` | confirmed |
| | | any other source that is not `VERIFIED` (`UNRECORDED`, an unknown value, or `OWNER_CONFIRMED` with no date) | `trade not verified` | `operar: sin verificar` | not on record |
| 6 | withdraw, not checked by the venue | source `OWNER_CONFIRMED` and `withdraw_confirmed_at` set | `withdraw confirmed {date}` | `retiros: confirmado el {date}` | confirmed |
| | | any other source that is not `VERIFIED` | `withdraw not verified` | `retiros: sin verificar` | not on record |
| 7 | information button | a tag carries a confirmation date | the last item of the list, a button and not a tag | | |

"Confirmed" and "not verified" are two rows of the same fact, so they MUST NEVER
be shown together for one fact. "Not verified" MUST be shown only for a fact
with nothing on record. A source value the panel does not know MUST be shown as
not verified and never as checked.

The three looks MUST differ by more than colour: **checked** is filled
(`border-rule bg-panel-2 text-ink-2`) and says the exchange itself showed the
fact to the application; **confirmed** is hollow and dashed
(`border-dashed border-rule-strong text-ink-2`) and says the owner's word with
the day he gave it; **not on record** is hollow, dashed and dimmer
(`border-dashed border-rule-strong text-ink-3`).

The information button MUST be named "About what you confirmed" and, when open,
MUST show: "'Confirmed' is what you told this panel on that day. {x} does not
let the panel check what a key may do, so orders are sent on your confirmation.
If the key cannot trade futures, {x} rejects the first live order and you get a
Telegram alert. Nothing checks the withdrawal setting."

A card MUST NOT show a full key, a secret, or a raw permission payload.

#### Scenario: A Bybit key checked by the venue

- GIVEN Bybit's key ends in `7Q2d`, was validated on 2026-10-02, trades, has a `VERIFIED` withdraw check and `internal_transfer` true
- WHEN the card renders
- THEN the key line reads `key ••••7Q2d` with `checked Oct 2, 2026`, and the tags are `trades`, `no withdrawal`, `transfers`, all filled, with no information button

#### Scenario: The key hint is a paragraph that never holds more than four characters

- GIVEN any stored key
- WHEN the card's markup is read
- THEN the hint is a `<p>` that cannot break inside, the card has exactly one heading while no form is open, and nothing in the document, attributes included, holds more than the last four characters of the key

#### Scenario: The hint is read in words

- GIVEN a key ending in `7Q2d`
- WHEN its accessible text is read
- THEN it reads "key ending in 7Q2d", and the label, the dots and the characters are hidden from assistive technology

#### Scenario: The date stands beside the key and not among the tags

- GIVEN a key with `validated_at` set, and a key with it null
- WHEN each card renders
- THEN the first reads "checked {date}" beside the hint, the second "not validated", and neither is a tag

#### Scenario: The tags wrap whole and carry no separator

- GIVEN any stored key
- WHEN the card's structure is read
- THEN the facts are one list that wraps, each tag cannot break inside, and the card's text contains no " · "

#### Scenario: A fact is said by one tag

- GIVEN Binance's key with both facts owner-confirmed on Oct 2, 2026
- WHEN the card renders
- THEN exactly one tag says trade (`trade confirmed Oct 2, 2026`), exactly one says withdrawal (`withdraw confirmed Oct 2, 2026`), and neither "trade not verified" nor "withdraw not verified" is on the card

#### Scenario: A confirmation with no date reads as not verified

- GIVEN a key whose trade source is `OWNER_CONFIRMED` and whose `trade_confirmed_at` is null
- WHEN the card renders
- THEN it shows `trade not verified` and not "confirmed"

#### Scenario: A key with no recorded facts is not validated and not confirmed

- GIVEN a key sealed before facts were recorded (both sources `UNRECORDED`, `validated_at` null)
- WHEN the card renders
- THEN it reads `not validated` beside the key, shows the dimmer dashed tags `trade not verified` and `withdraw not verified`, no confirmation date, no information button, and, on a served exchange, in the neutral weak ink, "Stored before the system recorded how a key was checked. Enter it again to have it checked."
- AND nothing on the card is amber

#### Scenario: A source the panel does not know is not drawn as checked

- GIVEN a key whose withdraw source is a value the panel does not know
- WHEN the card renders
- THEN it shows `withdraw not verified` and not `no withdrawal`

### Requirement: A Binance Permission Is Never Stated As A Fact The Application Checked

> **Replaces 2026-10-10 (owner decisions 24, 30 and 55).**

"Confirmed" is the owner's word and "checked" is the application's. A card MUST
NOT show `trades` or `no withdrawal` for a fact whose source is
`OWNER_CONFIRMED`, and MUST NOT show a Binance withdrawal as anything but
"withdraw confirmed {date}" or "withdraw not verified". The only filled tag of a
Binance key MUST be `reads`, because the signed read passing is the one thing
Binance itself showed.

#### Scenario: A confirmed Binance key never reads as checked

- GIVEN Binance's key was saved with both confirmations
- WHEN the card renders
- THEN the tags are `reads`, `trade confirmed {date}`, `withdraw confirmed {date}` and the information button, and neither `trades` nor `no withdrawal` is on the card

#### Scenario: The same key's tags differ in more than colour

- GIVEN the same card
- WHEN the tags are read as text
- THEN the filled tag and the two dashed tags are told apart by their words ("reads" against "confirmed" with a date)

### Requirement: Amber Marks Only Where The Owner Has Something To Do

> **Replaces 2026-10-10 (owner decisions 20 and 55).**

Amber MUST appear only on the `read-only` tag, on the `no key` tag of a
degraded exchange, and, with each of them, on the card's border and sentence.
The `no key` tag of an empty exchange, "not validated", the "confirmed" tags,
the "not verified" tags and the not-served sentence MUST be neutral. The form
MUST contain no amber. The files that use an amber utility MUST be exactly
`shared/credentials/KeyMark.tsx` and `features/settings/ExchangeKeyCard.tsx`
among the Settings files, and the panel's existing test of allowed amber files
MUST list exactly those two.

#### Scenario: Only a state that needs an action is amber

- GIVEN cards in each state
- WHEN their classes are read
- THEN amber is on the read-only and degraded cards' tag, border and sentence and on no other card, tag or sentence

#### Scenario: The list of amber files is exact

- GIVEN the source files of the panel
- WHEN the allowed-amber test runs
- THEN the two files above are the only Settings files that use an amber utility

### Requirement: An Exchange The Panel Does Not Serve Has No Buttons

> **Added 2026-10-10 (owner decisions 31, 54 and 58).**

An exchange that is not in the served file (Pionex) MUST be shown whether or
not it has a key, and MUST have no "Add key", "Replace key" or "Delete key". With
a stored key its card MUST show its state as for any exchange, then, in weak
ink: "The {x} key is managed outside this panel, on the server. It cannot be
added, replaced or deleted here." Without a key its card MUST show the `no key`
tag as its only second line, "No key stored." and then the same sentence, amber
only when a pool of it is on.

#### Scenario: A Pionex key is shown without buttons

- GIVEN Pionex has a stored key and is not in the served file
- WHEN Settings renders
- THEN the card shows the key hint and facts as for any exchange, the sentence that the key is managed outside the panel, and no button

#### Scenario: A Pionex card exists without a key

- GIVEN Pionex has pool rows and no stored key
- WHEN Settings renders
- THEN the card reads "No key stored." and the managed-outside sentence, shows the `no key` tag, and has no button
- AND the tag is amber only if a Pionex pool is enabled

### Requirement: The Exchange Tabs Carry The Key State

> **Added 2026-10-10 (owner decisions 20, 22, 55). Replaces the tab mark text
> of 2026-09-25.**

Each exchange tab MUST read the same state as its card (the same function, the
same inputs) and MUST show under its name: nothing for a key that trades;
`read-only` in amber for a key that cannot trade; `no key` in amber for no key
with a pool on; `no key` in grey for no key and no pool on (a deleted key, or an
exchange never keyed). While `GET /api/credentials` is loading or failed, a tab
MUST show its name alone, and MUST NOT show any mark, because no mark is a claim
of nothing. The mark MUST be a word, never colour alone, and MUST be part of the
tab's accessible name ("binance no key"). The tab of a deleted key MUST stay.

The name MUST sit at the same place in every tab, with or without a mark: every
tab's inner element is a grid of three rows whose outer two rows are the same
track, the name is the middle row, a mark is the third row, and a tab without a
mark holds one element. Every tab MUST be 52 px tall; the bar from the large
breakpoint MUST keep its height. Settings MUST show no exchange tabs.

#### Scenario: Each state's mark on a tab

- GIVEN exchanges in each state of the table and the credentials read answered
- WHEN the tabs render, in the bar and in the phone row
- THEN each shows the mark above and no other, and the amber ones carry the amber utility

#### Scenario: No mark while the keys load or fail

- GIVEN `GET /api/credentials` is loading, then failed
- WHEN the tabs render
- THEN every tab shows its name alone, in both cases

#### Scenario: The mark is in the accessible name

- GIVEN Binance has no key
- WHEN its tab's accessible name is read
- THEN it is "binance no key"

#### Scenario: A mark does not move the name

- GIVEN one tab with a mark and one without
- WHEN their structure is read
- THEN both inner elements carry the same three grid classes, the name has the same class list and the middle-row placement in both, the mark has the third-row placement, and the unmarked tab has exactly one element in its grid

#### Scenario: A deleted key's tab stays and is grey

- GIVEN Bybit's key was deleted, so its pool is disabled
- WHEN the tabs render
- THEN Bybit's tab is present with `no key` in grey, not amber

#### Scenario: A shell render proves the credentials read is answered

- GIVEN a shell test with the default test harness
- WHEN it renders the tabs
- THEN the harness answered `GET /credentials`, no request was rejected as unexpected, and no tab has a mark

### Requirement: On A Phone The Exchange Tabs Share The Row's Whole Width

> **Added 2026-10-10 (owner decision 59).**

Below the large breakpoint, every tab MUST take the same share of the row and be
centred in it, and MUST NOT be squeezed under its own name or mark; when the
tabs do not fit, the row MUST scroll sideways and MUST NOT wrap. From the large
breakpoint the tabs MUST keep their own width. A tab MUST carry the utilities
that give an equal share (`flex-1`), a minimum of its content (`min-w-fit`), and
its own width from the large breakpoint (`lg:flex-none`), and MUST NOT carry
`shrink-0`.

#### Scenario: The tabs share the row

- GIVEN a phone width and two exchanges
- WHEN the tab row's structure is read
- THEN every tab carries `flex-1`, `min-w-fit` and `lg:flex-none`, none carries `shrink-0`, and the row keeps its sideways scroll and does not wrap

#### Scenario: The same component serves both surfaces

- GIVEN the bar from the large breakpoint and the row below it
- WHEN either is rendered
- THEN both are the same component and both carry the marks

### Requirement: The Key Form Opens Inside Its Card, One At A Time

> **Replaces 2026-10-10 (owner decisions 54 and 57).** September's "Settings
> Shows the Validation Outcome On Add/Replace" is withdrawn.

"Add key" and "Replace key" MUST be one element that opens and closes the key
form of its card; it MUST carry `aria-expanded` and `aria-controls`, and it MUST
stay mounted when its text changes. The form MUST open inside its card, under
the facts and the buttons, as a section named by its title, not as a dialog,
and the page MUST hold at most one open form. Opening the form of another card,
or pressing the button that opened it, MUST close the open one and empty it.
Leaving Settings MUST close it. While a save is in flight every button of every
card MUST be disabled, and while a card's form is open its "Delete key" MUST be
disabled.

The form MUST hold, in this order: the title ("Add a {x} key", or "Replace the
{x} key" when a key is stored); two fields, "API key" and "API secret"; the help
("Before saving, the key is tried with a real read at {x}. A key that can
withdraw funds is refused. A key that cannot trade is saved with a warning." for
an exchange with no confirmations, or "Before saving, the key is tried with a
real read at {x}. {x} does not let this panel check what the key may do, so you
confirm it here." for one with them); only when a key is stored, "Saving
replaces the key stored now, also when the new key cannot trade."; the
confirmations; the refusal when there is one; and the buttons "Check and save"
and "Close". The title MUST be an `h4`. The panel MUST check nothing about the
key beyond both fields having text. The form MUST have no Escape handling.

#### Scenario: One form at a time

- GIVEN the Bybit form is open with text typed in it
- WHEN the owner presses "Add key" on Binance's card
- THEN Bybit's form is gone, Binance's is open, and reopening Bybit's shows two empty fields

#### Scenario: The opening button closes its own form

- GIVEN a form is open
- WHEN the owner presses the button that opened it
- THEN the form closes, its fields are emptied on reopening, and the focus is on that button

#### Scenario: Opening the form puts the focus in the key field

- GIVEN a card with no open form
- WHEN the owner opens its form
- THEN the focus is in "API key"

#### Scenario: A replace form warns about replacing

- GIVEN Bybit has a stored key
- WHEN the owner opens its form
- THEN the title is "Replace the Bybit key" and the note "Saving replaces the key stored now, also when the new key cannot trade." is shown, and an exchange with no key shows neither

#### Scenario: The submit button follows what is typed

- GIVEN an open form
- WHEN a field is empty, or a required box is unticked, then both fields have text and every box is ticked
- THEN "Check and save" is disabled, then enabled

#### Scenario: Close is the second button's word

- GIVEN an open form
- WHEN its buttons are read
- THEN they are "Check and save" and "Close", and neither is ever "Cancel" or "Saved"

### Requirement: The Form Asks For The Confirmations Its Exchange Requires

> **Replaces 2026-10-10 (owner decisions 24 and 30).**

For an exchange with confirmations in the served file (Binance) the form MUST
show a group titled "What you checked in {x}" with one real checkbox per name,
each unticked: "I confirmed in {x} that this key has withdrawals disabled" and
"I confirmed in {x} that this key has Enable Futures", followed by "If the key
lacks Enable Futures, {x} rejects the first live order and you get a Telegram
alert. Nothing checks the withdrawal setting: it rests on your word." The
submit MUST be disabled until both are ticked, and the request MUST carry both as
`true`. For Bybit the form MUST show no confirmation and the request MUST carry
no confirmation field. The request body MUST be `{api_key, api_secret}` plus the
confirmations, with no `label`.

#### Scenario: A Binance key cannot be submitted without both confirmations

- GIVEN both fields have text and at most one box is ticked
- WHEN the form is read
- THEN "Check and save" is disabled

#### Scenario: A Binance request carries both confirmations

- GIVEN both fields have text and both boxes are ticked
- WHEN the owner presses "Check and save"
- THEN one `PUT` is sent with `api_key`, `api_secret`, `withdrawals_disabled_confirmed: true` and `futures_enabled_confirmed: true`

#### Scenario: A Bybit form shows and sends no confirmation

- GIVEN the Bybit form with both fields filled
- WHEN it is read and submitted
- THEN it shows no checkbox and the body holds only `api_key` and `api_secret`

#### Scenario: The Binance help does not claim more than is true

- GIVEN the Binance form
- WHEN its help is read
- THEN the Enable Futures consequence and the unchecked withdrawal setting are stated apart, and no text says that a wrong withdrawals confirmation is caught by the venue

### Requirement: Every Refusal Has A Text Chosen By The Panel, Never The Server's

> **Replaces 2026-10-10 (design addendum, section F).**

The form's refusal MUST be a `role="alert"` in the loss colour, chosen by the
response's `outcome` or status, and MUST NOT render the server's `detail`. A
refusal MUST be followed by "The fields were emptied. Enter the key again to
retry." Typing MUST NOT remove it; the next attempt or closing the form MUST.
After a refusal the focus MUST move to "API key". The texts, `{x}` being the
exchange's name:

| Answer | Key under `settings.form.error.` | EN text |
| --- | --- | --- |
| 422 `KEY_REJECTED` | `keyRejected` | "{x} did not accept this key. Check that the key and the secret were copied whole, that the key has not expired, and that it allows this server's IP address. Nothing was saved." |
| 422 `WITHDRAW_PERMISSION` | `withdrawPermission` | "This key can take funds out of the account, so it was refused. Create a key without withdrawal permission and enter that one. Nothing was saved." |
| 422 `PERMISSIONS_UNAVAILABLE` | `permissionsUnavailable` | "{x} did not say what this key is allowed to do, so it was not saved. Try again in a moment." |
| 502 `VENUE_UNREACHABLE` | `venueUnreachable` | "{x} could not be reached, so the key was not checked and not saved. Nothing is known to be wrong with it. Try again." |
| 409 `CONCURRENT_SAVE` | `concurrentSave` | "Another save for {x} finished first, so this one was not stored. The card shows the key that is stored now. Check it before saving again." |
| 422 `CONFIRMATION_REQUIRED` | `confirmationRequired` | "The key was not saved, and nothing was sent to {x}, because a confirmation is missing:" then one line per name in `missing`, each the checkbox's own label |
| 422 `CONFIRMATION_REQUIRED`, `missing` not a list of known names | `confirmationRequiredUnlisted` | "The key was not saved, and nothing was sent to {x}, because a confirmation is missing. Tick both and enter the key again." |
| 422 `CONFIRMATION_NOT_APPLICABLE` | `confirmationNotApplicable` | "The panel sent a confirmation that {x} does not take, so the key was not saved. Reload the page and enter the key again." |
| 404 | `notServed` | "{x} keys are not managed by this panel, so nothing was saved." |
| 503 | `storageUnavailable` | "The server cannot store keys right now, so nothing was saved. If this repeats, the server's encryption key is missing or unusable and has to be fixed there." |
| 422, `detail` a list, an entry whose `loc` ends in `api_key` | `invalidKey` | "The API key cannot be stored as typed. A key has 4 to 256 characters and no spaces or accented letters. Nothing was sent to {x}." |
| 422, `detail` a list, an entry whose `loc` ends in `api_secret` and none for the key | `invalidSecret` | "The API secret cannot be stored as typed. A secret has at most 256 characters and no spaces or accented letters. Nothing was sent to {x}." |
| 422, `detail` a list, neither | `invalidRequest` | "The server refused the request as malformed, so nothing was saved. Reload the page and enter the key again." |
| no answer (status 0) | `noAnswer` | "No answer came back from the server, so it is not known whether the key was saved. The card shows what is stored now." |
| any other status, a 500 included | `unknown` | "The save ended in a way this panel cannot read (status {status}), so it is not known whether the key was saved. The card shows what is stored now." |
| 401 | none | none: the token gate takes the page |

The refusal for `CONFIRMATION_REQUIRED` MUST name which confirmation is missing.
For `noAnswer` and `unknown` the panel MUST NOT treat the attempt as a save that
worked, MUST keep the form open, and MUST read both lists again so the card shows
what is stored now.

#### Scenario: Each answer shows its own text

- GIVEN the form is submitted and the server answers each row of the table
- WHEN the refusal is read
- THEN it equals the row's English text (`{status}` filled for `unknown`), and nothing stored is changed by the panel

#### Scenario: A missing confirmation is named

- GIVEN the server refuses a Binance save with `missing` holding `futures_enabled_confirmed`
- WHEN the refusal is read
- THEN it lists "I confirmed in Binance that this key has Enable Futures" and not the other box

#### Scenario: The server's wording is never rendered

- GIVEN every refusal is answered with a `detail` that contains the typed key and secret, the pydantic one with an `input` field that does, and a network failure whose message does
- WHEN the document's text is read
- THEN it holds neither the typed key nor the typed secret

#### Scenario: A save with no answer is said to be unknown

- GIVEN the request fails with no answer
- WHEN the attempt ends
- THEN the form stays open and empty with the `noAnswer` text, both lists are read again, and no "saved" notice is shown

### Requirement: The Form Is Emptied After Every Attempt

> **Replaces 2026-10-10 (owner decision 54, not reopened).**

After every attempt, a save that worked and a refused or unread one included,
both fields MUST be emptied and the boxes unticked. While the request is in
flight the button MUST read "Checking…", be disabled, and the fields MUST be
read-only; "Close" MUST be disabled. A second click or Enter while it is in
flight MUST send no second request, and a failed save MUST NOT be retried.

#### Scenario: Both fields are empty after every ending

- GIVEN a save that worked, each refusal, a network failure and a 401
- WHEN each attempt ends
- THEN neither field holds text, asserted on both, and the boxes are unticked; after the save that worked the form is gone and reopening it shows two empty fields

#### Scenario: A second click sends nothing

- GIVEN a save is in flight
- WHEN the owner clicks the button again or presses Enter
- THEN exactly one `PUT` has been sent

#### Scenario: A failed save is not retried

- GIVEN a save fails
- WHEN time passes
- THEN exactly one `PUT` was sent

#### Scenario: Close is disabled while checking

- GIVEN a save is in flight
- WHEN the form is read
- THEN "Close" is disabled and the button reads "Checking…"

### Requirement: After A Save That Worked The Form Closes And The Card Says So

> **Added 2026-10-10 (owner decision 57).** Replaces September's "success
> shows the resulting last-4 in the form" and the read-only warning in the form.

When a save works, the form MUST close on the answer, without waiting for the
lists. The card MUST say "Key ending in {last4} saved." (or "Key saved." when the
answer's `last4` is not exactly four characters, or absent) as the first line of
its facts, a plain paragraph that is not a live region, until the next thing the
owner does on the page (opening a form, opening the delete dialog, another save,
or leaving); it MUST NOT use a timer. The `last4` MUST come from the answer and
never be cut from what was typed.

Until `GET /api/credentials` has been read again, and when that read fails, the
card MUST be drawn from the save's answer and MUST NOT show the key stored before
as current: the key line is the saved key's hint with no date; the only tag is
`read-only` when the answer said the key cannot trade (`warnings` holds
`READ_ONLY_KEY`, or `facts.trade_capable` is false); and the notice reads "Key
ending in {last4} saved. The rest of this card appears when the list has been
read again." A failed read MUST also show the stale-list line above the cards.
"Delete key" MUST appear only once the list is read again.

The read-only warning MUST be the card's own state: the amber `read-only` tag, the
amber border and the read-only sentence, drawn from the answer while the list is
behind and from the list afterwards. The form MUST carry no warning of its own.

The keyboard focus MUST move, after the form has left the document, to the card's
toggle, which reads "Replace key" from the answer alone, also for a first key.
"Delete key" MUST NOT take the focus.

The page MUST hold one status region (`role="status"`), hidden from sight and
always in the document. On a save it MUST say "Key ending in {last4} saved.",
followed by the card's read-only sentence for a key that cannot trade; the same
region says "{x} key deleted." after a delete.

#### Scenario: The form closes on the answer

- GIVEN the owner submits a valid key
- WHEN the answer is a 200
- THEN the form is gone, and both lists are read again

#### Scenario: The card says it, and the old key is not shown meanwhile

- GIVEN Bybit has a stored key ending `AAAA` and the owner replaces it, the answer says `last4` is `BBBB`, and the credentials list has not been read again
- WHEN the card renders
- THEN it shows `key ••••BBBB` with no date, the notice with "The rest of this card appears when the list has been read again.", and `AAAA` appears nowhere, including when the re-read fails

#### Scenario: Once the list is read the card is the list's, with the notice

- GIVEN the list was read again after the save
- WHEN the card renders
- THEN it is the card of its state, with "Key ending in BBBB saved." as the first line of its facts, and "Delete key" is offered

#### Scenario: A read-only key is a state of the card

- GIVEN the owner saves a key whose answer says it cannot trade
- WHEN the form closes
- THEN the card shows the amber `read-only` tag, the amber border and the read-only sentence, drawn from the answer even if the list has not been read, and the tab shows `read-only` once the list is read

#### Scenario: The focus goes to the toggle

- GIVEN a first key is saved for Binance
- WHEN the form has closed
- THEN the active element is the card's toggle, which reads "Replace key", and it is the same element that read "Add key"

#### Scenario: The status region tells a screen reader

- GIVEN a key that cannot trade is saved
- WHEN the form closes
- THEN the status region says "Key ending in {last4} saved." followed by the read-only sentence, and the card's visible notice is not a live region

#### Scenario: The last four come from the answer

- GIVEN the answer's `last4` differs from the end of the typed key, and in another run is the whole typed key
- WHEN the status and the card are read
- THEN the first says and draws the answer's four characters, the second says "Key saved." and the document holds no typed key

#### Scenario: The notice has no timer

- GIVEN a save notice is on a card
- WHEN time passes and then the owner opens a form
- THEN the notice stays until the form opens, and is gone after

### Requirement: The Typed Secret Lives Only In Its Two Fields

> **Added 2026-10-10 (design addendum, section H, owner decision 54).**

The "API key" and "API secret" fields MUST be uncontrolled: no `value` and no
`defaultValue`, no `name`. "API key" MUST be `type="text"` with
`autoComplete="off"`, `spellCheck={false}`, `autoCapitalize="off"` and
`autoCorrect="off"`; "API secret" MUST be `type="password"` with
`autoComplete="new-password"`. Component state MUST hold only whether each field
has text, which boxes are ticked, the phase and the result of the last attempt.
The save MUST be a plain function that never throws and never returns the error
object; it MUST NOT be a mutation. The typed text MUST be nowhere else:

| Place | Rule |
| --- | --- |
| a query's key, data or error | never |
| the mutation cache | no entry exists for a save |
| React state | none; the fields are uncontrolled |
| a DOM attribute, or the document's markup | never; neither field has a `value` attribute |
| a rendered error text | never; the server's `detail` is not rendered |
| the console | nothing in Settings or the credentials client writes to it, and the save never rejects |
| the URL or query string | never; the key and secret travel in the body of one `PUT` |
| `localStorage`, `sessionStorage` or any persisted store | never |
| a status region or an `aria-label` | only the answer's four characters |

#### Scenario: No query cache entry holds the key or the secret

- GIVEN sentinels `K` and `S` typed into the fields
- WHEN each ending (a save, each refusal, a network failure, a 401) has happened
- THEN a walk of every query's key, data and error finds neither

#### Scenario: No mutation cache entry exists for a save

- GIVEN a save of each ending
- WHEN the mutation cache is read
- THEN it holds no entry for the save, and the form and the credentials client never pass the save to `useMutation`

#### Scenario: The fields are uncontrolled

- GIVEN the form's source
- WHEN it is read
- THEN neither field has `value=` or `defaultValue=`, neither has a `name`, and each carries exactly the attributes above

#### Scenario: No attribute of the document holds the key or the secret

- GIVEN `K` and `S` typed, and again after each ending
- WHEN the document's markup is read
- THEN it holds neither and no field has a `value` attribute

#### Scenario: Nothing is written to the console

- GIVEN each ending
- WHEN the console spies are read
- THEN none was called, no source of Settings or the credentials client calls `console.`, and the save resolves for a `fetch` that throws a plain error

#### Scenario: The request is one PUT with the secret only in its body

- GIVEN a submitted form
- WHEN the requests are listed
- THEN there is one `PUT` to the exchange's path with no query string, carrying the key and the secret in its body only

#### Scenario: No storage holds what was typed

- GIVEN each ending
- WHEN `localStorage` and `sessionStorage` are read
- THEN neither holds `K` or `S`

#### Scenario: Closing, leaving and switching empty the fields

- GIVEN text typed in a form
- WHEN the owner closes it, leaves Settings and returns, or opens another exchange's form
- THEN no form is open or the other one is, and reopening shows two empty fields

#### Scenario: A 401 in the middle of a save leaves nothing typed

- GIVEN a save is answered 401
- WHEN the token gate takes the page and the owner unlocks it
- THEN no form is open, neither sentinel is in the document, and nothing was recorded, re-read or focused for the save

#### Scenario: A save result holds only known fields

- GIVEN a result from the save function
- WHEN its own properties are listed
- THEN they are the known fields of `saved`, `refused` or `unauthorized`, and `last4` is kept only when it is exactly four characters

#### Scenario: The fields ask the browser to keep nothing

- GIVEN the form
- WHEN each field's attributes are read
- THEN they are the ones above, attribute by attribute

#### Scenario: What a browser does with the fields is reviewed by eye

- GIVEN the form in a real browser
- WHEN the owner types a key
- THEN the review by eye records whether the browser offers to save it as a login, because no attribute prevents the offer and no automated test can see it

### Requirement: Deleting A Key Is Confirmed With A Plain Button And A Refusal Is Stated

> **Replaces 2026-10-10 (owner decisions 22 and 54).** The confirmation is a
> plain button in a dialog; the owner types nothing.

A served card with a stored key MUST offer "Delete key", always enabled while
shown; one click MUST only open a dialog and MUST send no request. The dialog
MUST be a native modal dialog labelled by its title "Delete the {x} key?", with
the body "The key ending in {last4} is removed from this system. {x} is no
longer read or traded from here until a key is added again. Its history stays."
and "The server allows this only while every {x} strategy is disabled and
nothing is open on it." Its buttons MUST be, in the document's order, "Cancel"
(focused when the dialog opens) and "Delete key", each at least 44 px tall;
"Delete key" reads "Deleting…" while the request is in flight, both buttons are
then disabled, and nothing closes the dialog (Escape included) until it settles.
Closing MUST return the focus to the card's "Delete key". The delete MUST be a
mutation over `DELETE /api/credentials/{exchange}`, which carries no secret, and
on every settled attempt MUST read `GET /api/credentials` and `GET /api/pools`
again and wait for them before it reports.

| Answer | What the owner sees |
| --- | --- |
| 200 | The dialog closes; the card is the empty card; the status region says "{x} key deleted."; the focus goes to that card's "Add key"; the tab reads `no key` in grey |
| 409 `EXCHANGE_NOT_FLAT` | In the loss colour, `role="alert"`: "The {x} key cannot be deleted yet. This is in the way:" and one line per non-empty list; both buttons stay |
| 409 whose five lists cannot all be read | "The {x} key cannot be deleted yet: a strategy is still enabled, a position is open or an order is in progress." and no list |
| 404 | "The server found no {x} key to delete. Close this: the card shows what is stored now." Not treated as a success |
| no answer, or any other status | "The delete ended in a way this panel cannot read. Close this: the card shows whether the key is still stored." |
| 401 | The token gate takes the page |

The lines, read from the response body, MUST be, with strategy names as text and
never links, and ids of allocations, reservations and attempts counted and never
listed:

| Field | EN text |
| --- | --- |
| `enabled_strategies` | one: "{count} enabled strategy: {names}. Disable it first." / other: "{count} enabled strategies: {names}. Disable them first." |
| `symbols` | "Open position on: {symbols}. It has to be closed first." |
| `allocations` | one: "{count} open allocation. It ends when its position is closed." / other: "{count} open allocations. They end when their positions are closed." |
| `live_reservations` | one: "{count} live reservation: capital held for an order. Wait for it to finish, then try again." / other: "{count} live reservations: capital held for orders. Wait for them to finish, then try again." |
| `in_flight_attempts` | one: "{count} order being placed right now. Wait for it to finish, then try again." / other: "{count} orders being placed right now. Wait for them to finish, then try again." |

#### Scenario: A single click sends nothing

- GIVEN Bybit has a stored key
- WHEN the owner clicks "Delete key" once
- THEN the dialog opens with "Cancel" focused and no `DELETE` has been sent

#### Scenario: The confirmation is a plain button

- GIVEN the dialog is open
- WHEN the owner presses "Delete key" in it
- THEN one `DELETE /api/credentials/bybit` is sent, with nothing typed first

#### Scenario: A refused delete states why and keeps the key

- GIVEN Bybit has a stored key, one enabled strategy named "Alpha" and an open position on `SOLUSDT`
- WHEN the owner confirms and the server answers 409 `EXCHANGE_NOT_FLAT`
- THEN the dialog shows "1 enabled strategy: Alpha. Disable it first." and "Open position on: SOLUSDT. It has to be closed first.", both buttons stay, and Bybit's card still shows its key

#### Scenario: Never half a list

- GIVEN a 409 whose lists cannot all be read
- WHEN the dialog shows it
- THEN it shows the sentence with no list

#### Scenario: A successful delete leaves the empty card and the tab

- GIVEN Bybit's strategies are all disabled and nothing is open
- WHEN the owner confirms and the server answers 200
- THEN the dialog is closed, the card is the empty card with "Add key", Bybit's tab stays with a grey `no key`, the status region says "Bybit key deleted.", and the focus is on "Add key"

#### Scenario: A 404 is not a success

- GIVEN the server answers 404
- WHEN the dialog shows it
- THEN it reads the 404 text and the card is read again, and the panel does not report the key as deleted

#### Scenario: A delete with no readable answer says the key may be gone

- GIVEN the delete fails with no answer
- WHEN the dialog shows it
- THEN it reads the unknown text, and the card is read again

#### Scenario: The dialog cannot be dismissed mid-request

- GIVEN the delete is in flight
- WHEN the owner presses Escape or either button
- THEN the dialog stays open

#### Scenario: Deleting leaves no secret in any cache

- GIVEN a delete of any ending
- WHEN the mutation cache is read
- THEN it holds no key or secret, because the request carried none

### Requirement: Settings Is Operable By Keyboard And Named For Assistive Technology

> **Added 2026-10-10 (design addendum, section I).**

Settings MUST have the heading order `h1` "Settings", `h2` "Exchange keys" with
the intro "One key per exchange. Keys are encrypted on the server and never
shown again; you only see the last four characters.", then each card's `h3`, and
an open form's `h4`. The cards MUST be a list. A card's document order MUST be:
name, key hint, date (or the `no key` tag), the save notice, the tags, the
information button, the sentences, "Add key" or "Replace key", "Delete key", then
the form. Each button MUST be named with its exchange ("Replace key Bybit") while
its visible text stays the start of the name. Each field MUST have a `<label>`
and be described by the help; the confirmations MUST be a `<fieldset>` with a
`<legend>`. Enter in a field MUST submit through a `<form noValidate>` whose
handler prevents the native submission. A refusal MUST be read when it appears.
Targets MUST be at least 44 px tall. No state MUST be carried by colour alone.
Dates MUST be UTC days in the panel's language.

#### Scenario: The headings are in order

- GIVEN Settings with all cards and one open form
- WHEN the headings are listed
- THEN they are `h1`, `h2`, one `h3` per card and the form's `h4`, with no heading between a card's name and its facts

#### Scenario: Buttons carry their exchange

- GIVEN Bybit and Binance cards
- WHEN the buttons are listed by accessible name
- THEN they read "Replace key Bybit" and "Add key Binance" and not the same name twice

#### Scenario: A refusal is an alert and the focus is where the owner types next

- GIVEN a refused save
- WHEN the form is read
- THEN the refusal has `role="alert"` and the focus is in "API key"

#### Scenario: Enter submits through the handler

- GIVEN both fields have text and the boxes are ticked
- WHEN the owner presses Enter in a field
- THEN one request is sent through the form's handler and the native submission is prevented

### Requirement: Every Settings Text Exists In English And Spanish

> **Added 2026-10-10 (design addendum, section J).**

Every text of Settings, the card, the tags, the marks, the form, the refusals,
the delete dialog and the status region MUST exist in `en.json` and `es.json` and
be resolved through i18n, with no hardcoded display text. The Spanish MUST
address the owner as "usted", as `es.json` already does ("Elija", "Escriba", "Pegue"; for example "Sobre lo que usted confirmó", "usted recibe"),
never as "tú" or "vos". The Spanish of the marks and tags MUST be exactly: `solo lectura`,
`sin clave`, `opera`, `lee`, `sin retiros`, `transfiere`, `sin transferencias`,
`operar: confirmado el {date}`, `retiros: confirmado el {date}`, `operar: sin
verificar`, `retiros: sin verificar`; the card's labels `clave`, `clave terminada
en {last4}`, `comprobada el {date}`, `sin validar`, `Lo que se sabe de esta
clave`, `Sobre lo que usted confirmó`; and the notices `Clave terminada en {last4}
guardada.`, `Clave guardada.` and `El resto de esta tarjeta aparece cuando la
lista se haya leído de nuevo.` The Spanish of the other texts is written at
build time in the same register. A date in a tag MUST be the panel's medium UTC
date, with no "on" in English and "el" in Spanish.

#### Scenario: The page, an open form and an open dialog read in Spanish

- GIVEN the locale is Spanish
- WHEN Settings, an open form and an open delete dialog are rendered
- THEN every text is Spanish and none of the English texts of this change is found

#### Scenario: The fixed Spanish is exact

- GIVEN the locale is Spanish and cards in each state
- WHEN the marks and tags are read
- THEN they equal the Spanish above

#### Scenario: The register is "usted"

- GIVEN every Spanish text added by Settings
- WHEN they are read
- THEN none addresses the owner as "tú" or "vos", and every imperative is a "usted" one

#### Scenario: Every new key exists in both files

- GIVEN the two locale files
- WHEN their Settings keys are compared
- THEN the sets are equal

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

#### Scenario: The operations table, dialog and fills are localized, with LONG and SHORT unchanged

> **Added 2026-10-04 (owner decisions 43 and 44).**

- GIVEN the locale is Spanish and a closed trades table, a rehearsal row's dialog and its fills table are on screen
- WHEN every visible string is read
- THEN the column headings, tags, sentences, dialog labels, fills labels and states are Spanish and sourced from i18n, and the operation's side reads "LONG" or "SHORT"

#### Scenario: The share control, "Saved", the Copy buttons and the win rate are localized

> **Added 2026-10-06 (owner decisions 44 and 48, design addendum "unit 12f").**

- GIVEN the locale is Spanish and a strategy detail view shows the share control with both information buttons open, a Save button that reads "Saved", the webhook block with both Copy buttons and a "By pair" table
- WHEN every visible string is read
- THEN each is the Spanish text of "The Detail Page's Follow-Up Texts Are Exactly These, In English And Spanish", sourced from i18n, with no leftover English

#### Scenario: The open-position views are localized

> **Added 2026-10-12 (owner decision 65).**

- GIVEN the locale is Spanish and the Strategies page, a strategy detail page and the Overview show open positions, an order in flight and a venue mark
- WHEN every visible string is read
- THEN each is the Spanish text of "Every Open-Positions Text Exists In English And Spanish", sourced from i18n, and `LONG` and `SHORT` are unchanged

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
existing admin token entry mechanism, consistent with how the panel's other
admin views are gated (revised 2026-10-16: the bookings view no longer exists).

#### Scenario: An ungated session cannot load panel data

- GIVEN no admin token has been entered in the current session
- WHEN a gated view attempts to load its data
- THEN the request is refused and the panel prompts for the token rather than showing partial data

### Requirement: The Navigation Has A Fourth Item, Discrepancies, With A Badge Of What Needs The Owner

> **Added 2026-10-16 (owner decision 66, "se le podria poner un badge de notificacion a su boton de la barra de navegacion cuando requiera revisarse"; Q7 answered (a); design addendum "PR 15" § H; prototype examples 1 to 3).**

The navigation MUST have a fourth item, `{ to: "/discrepancies", labelKey: "discrepancies", end: false }`, in the order Overview, Strategies, Discrepancies, Settings, in the side navigation and in the bottom bar. The route `discrepancies` MUST be registered inside the shell. The item MUST carry a badge beside its label, drawn by one `NavBadge` component used by both navs, that shows the count of the confirmed discrepancies that need the owner: red (`loss`) with its number, at the item's end, and nothing at zero. The number MUST be `aria-hidden` and a visually hidden span MUST carry the words, so that the item's accessible name is "Discrepancies, 1 discrepancy needs you" or "Discrepancies, 12 discrepancies need you" (Spanish: "Discrepancias, 12 discrepancias requieren su atención"). On a phone the bar MUST have four equal cells; the badge MUST be lifted to the cell's top-right corner; and every label of the bar MUST sit 8 px above the bottom edge, in all four cells, so the labels stay level whether or not a badge is drawn. "Discrepancias" at 375 px with two digits and the item active MUST fit. Amber MUST NOT be used (it already means dry run).

#### Scenario: Four items in order, no badge at zero

- GIVEN nothing needs the owner
- WHEN the side navigation renders
- THEN it lists Overview, Strategies, Discrepancies, Settings in that order, the Discrepancies item is a plain link with the accessible name "Discrepancies", and no badge is drawn

#### Scenario: The badge shows the count, red, with its words

- GIVEN 12 discrepancies need the owner
- WHEN either navigation renders
- THEN a red badge reads 12, and the item's accessible name is "Discrepancies, 12 discrepancies need you"

#### Scenario: One discrepancy uses the singular

- GIVEN 1 discrepancy needs the owner
- WHEN the navigation renders
- THEN the accessible name is "Discrepancies, 1 discrepancy needs you"

#### Scenario: The badge is the same in both navigations

- GIVEN a count above zero
- WHEN the side navigation and the bottom bar render
- THEN both draw the same `NavBadge` with the same count and name

#### Scenario: The bottom bar at 375 px keeps four cells and level labels

- GIVEN a phone viewport of 375 px, the Spanish language and 12 discrepancies needing the owner, the Discrepancies item active
- WHEN the bottom bar renders
- THEN four equal cells are drawn, the badge sits at the top-right corner of its cell, the label "Discrepancias" is not clipped, and the four labels sit at the same height whether or not a badge is drawn

#### Scenario: The badge is not amber

- GIVEN the badge is drawn
- WHEN its classes are read
- THEN it uses the `loss` colour token and no amber utility

### Requirement: The Badge Draws Nothing Unless It Can Say How Many Need The Owner

> **Added 2026-10-16 (owner decision 66; design addendum "PR 15" § H and § K rows 8 and 14; prototype examples 2, 8 and 9).**

The badge MUST count the items of `needs_owner` and NOTHING else: an item being booked and an automatic booking never count. It MUST read the same query as the page (`useConfirmedDiscrepancies`), so that the two cannot disagree. It MUST draw nothing while the query is loading and nothing when the first read failed (the nav cannot say "failed" without becoming a permanent alarm: the page says it, and Telegram does not depend on the panel). After a failed refresh it MUST keep the last count. It MUST draw nothing when `dry_run` is true.

#### Scenario: Nothing while loading

- GIVEN the query has not answered
- WHEN the navigation renders
- THEN no badge is drawn

#### Scenario: Nothing when the first read failed

- GIVEN the first read failed
- WHEN the navigation renders
- THEN no badge is drawn

#### Scenario: Being booked and bookings never count

- GIVEN one item in `being_booked`, two bookings and none in `needs_owner`
- WHEN the navigation renders
- THEN no badge is drawn

#### Scenario: The count equals the page's list

- GIVEN three items in `needs_owner`
- WHEN the navigation and the page render
- THEN the badge reads 3 and the page's "Needs you" list holds three items

#### Scenario: A failed refresh keeps the last count

- GIVEN a good read of two items and then a failed refresh
- WHEN the navigation renders
- THEN the badge still reads 2

#### Scenario: Dry run draws no badge

- GIVEN `dry_run` is true
- WHEN the navigation renders
- THEN no badge is drawn

### Requirement: The Discrepancies Page Reads One Query, Is Not Scoped To An Exchange And Groups By Exchange

> **Added 2026-10-16 (owner decision 66, Q6 answered (a); design addendum "PR 15" § H; prototype examples 4 to 7 and 11).**

`shared/api/discrepancies.ts` MUST fetch `GET /api/reconciliation/confirmed`, MUST check the shape of the whole body and refuse it whole if any element is malformed (the rule of the former `usePendingBookings` and of PR 14), and MUST expose `useConfirmedDiscrepancies` under the query key `["reconciliation", "confirmed"]`, refetched every 60 s and on focus like the open positions. The page `features/discrepancies/DiscrepanciesPage.tsx` MUST draw, in this order: the title "Discrepancies" and its sentence ("Where the exchange and the ledger still disagree after repeated comparisons. A close the system can attribute to one strategy is booked automatically; the rest is listed under Needs you."); the read line ("Last read {time} UTC" and the button "Read again"); the "Needs you" list; "Being booked", only when not empty; "Booked automatically". The page MUST read no exchange scope and the top bar MUST show no exchange tabs on it, so that a badge of 2 can never sit above an empty page. Within each list, items MUST be grouped by exchange, whatever exchange tab was last selected. Each discrepancy item MUST carry `id="discrepancy-<discrepancy_id>"`.

#### Scenario: A well-formed body is read

- GIVEN a well-formed body
- WHEN the module reads it
- THEN the three lists and the counts are available to the page and the badge

#### Scenario: One malformed element refuses the whole body

- GIVEN a body with one malformed element in `booked`
- WHEN the module reads it
- THEN the whole body is refused and the page shows its failed state

#### Scenario: A 404 is an error

- GIVEN the route answers 404
- WHEN the module reads it
- THEN it is an error, not an empty answer

#### Scenario: The page ignores the exchange tab

- GIVEN items on bybit and binance and the bybit tab last selected
- WHEN the page renders
- THEN items of both exchanges are drawn, each list grouped under an exchange name, and no exchange tabs are on the page

#### Scenario: The sections are in order

- GIVEN items in all three lists
- WHEN the page renders
- THEN the headings read "Needs you", "Being booked", "Booked automatically" in that order

#### Scenario: Each item can be reached by its hash

- GIVEN the location's hash is `#discrepancy-<id>`
- WHEN the page renders and when the hash changes
- THEN the item with that id is scrolled into view

#### Scenario: The badge and the page share one request

- GIVEN the navigation and the page are both mounted
- WHEN the network is read
- THEN one request to the route answers both

### Requirement: The Discrepancies Page States Its Read And Never Reads As An All-Clear Without Having Looked

> **Added 2026-10-16 (owner decision 66; design addendum "PR 15" § H and § K rows 8 and 14; prototype examples 4, 6, 8 and 9).**

The page MUST say its read state in these exact words:

- first read loading: "Reading discrepancies…" (`role="status"`), and no list;
- first read failed: "Discrepancies could not be read, so this page cannot say whether anything needs you." (`role="alert"`, `loss`) with the button "Read again", and no list: never "Nothing needs you";
- a later refresh failed: the last lists stay, with "Last read" and the time in `loss` and "Could not be refreshed since {time} UTC.", as PR 14's example 11d;
- `dry_run` true: "The comparison with the venue does not run in dry run, so nothing is checked here.", in the neutral strong rule, not amber, and NO list under it, not even an empty one;
- nothing in any list: under "Needs you", "Nothing needs you. The venue agrees with the ledger on every confirmed comparison.", and under "Booked automatically", "No booking in the last 30 days." so that the page shows it was looked at;
- something being booked and nothing needing the owner: under "Needs you" only "Nothing needs you.", because the second sentence would be false while a booking is under way; "Being booked" reads "Nothing here needs you. If it cannot be booked, it moves to Needs you.".

#### Scenario: Loading

- GIVEN the first read has not answered
- WHEN the page renders
- THEN "Reading discrepancies…" is drawn with `role="status"` and no list and no all-clear

#### Scenario: A failed first read never says nothing needs the owner

- GIVEN the first read failed
- WHEN the page renders
- THEN the alert sentence and "Read again" are drawn, no list is drawn, and the words "Nothing needs you" are absent

#### Scenario: A failed refresh keeps the lists

- GIVEN a good read and then a failed refresh
- WHEN the page renders
- THEN the last lists stay, "Last read" and its time are in `loss`, and "Could not be refreshed since 21:38:12 UTC." is drawn

#### Scenario: Dry run says the comparison does not run

- GIVEN `dry_run` is true
- WHEN the page renders
- THEN the sentence above is drawn in a neutral box and no list, empty or not, is drawn

#### Scenario: Nothing at all

- GIVEN all three lists are empty and `dry_run` is false
- WHEN the page renders
- THEN "Nothing needs you. The venue agrees with the ledger on every confirmed comparison." and "No booking in the last 30 days." are drawn

#### Scenario: A booking under way does not claim the venue agrees

- GIVEN one item in `being_booked` and none in `needs_owner`
- WHEN the page renders
- THEN "Needs you" says only "Nothing needs you."

### Requirement: A Needs-You Item Says What Is Wrong In Red, With Its Words, And What The Owner Can Do

> **Added 2026-10-16 (owner decision 66, Q3, Q7 and Q9; design addendum "PR 15" § H and § I; prototype examples 5, 8c and 10).**

Each "Needs you" item MUST show: the pair and the pool (`usdt-m · USDT`); a red sentence, with a red border on the item, being the reason's sentence or, for `NOT_BOOKABLE`, the kind's sentence; the kind in words when the red sentence is not already it; "Exchange", "Ledger" and "Difference" with the base currency and the signed difference (`-0.5`, `+12`); "Strategy" or "Strategies" with each name a link to the strategy, or "No strategy"; "Confirmed" with the date and time in UTC; "Last compared" with the time in UTC; and "What you can do". The sentences MUST be exactly:

- `NOT_BOOKED`: "Could not be booked automatically." and under it "The venue closed a position the ledger holds open.";
- `SEVERAL_ALLOCATIONS`: "The venue closed a position several strategies share; one booking cannot split it.";
- `AMBIGUOUS_PARTIAL_REDUCE`: "The venue reduced a position several strategies share; which one cannot be told.";
- `NO_MATCHING_ALLOCATION`: "The venue holds a position no strategy opened.".

"What you can do" MUST read, for `NO_MATCHING_ALLOCATION`, "Close it on the exchange by hand. The next comparison resolves it.", and for every other reason, "Ask for a manual reconciliation. Nothing in this panel can book it." The latter wording stands as the owner approved it; how a manual reconciliation is asked for is left for later (owner decision 66, left for later; follow-up cd.f1). The exact reason MUST NOT be requested from anywhere but the alert, since it is not stored.

#### Scenario: Every reason shows its sentence

- GIVEN four items, one per reason above
- WHEN the page renders
- THEN each shows its sentence in red and its "What you can do" text, and the item has a red border

#### Scenario: The nets and the difference are shown signed

- GIVEN a ledger of 0.5 SOL and an exchange of 0 SOL
- WHEN the item renders
- THEN it reads Exchange 0 SOL, Ledger 0.5 SOL, Difference -0.5 SOL

#### Scenario: Several strategies are links

- GIVEN an item with two allocations
- WHEN it renders
- THEN the label is "Strategies" and each name links to its strategy

#### Scenario: A null strategy name reads as unknown

- GIVEN an allocation with `strategy_name` null
- WHEN the item renders
- THEN it reads "unknown strategy" and is not a link to nothing

#### Scenario: No strategy

- GIVEN an item with no allocations
- WHEN it renders
- THEN it reads "No strategy"

#### Scenario: The red always has words

- GIVEN any red item
- WHEN it is read by assistive technology
- THEN its sentence is text on the page, not a colour alone

### Requirement: A Being-Booked Item Is Neutral And Says So

> **Added 2026-10-16 (owner decision 66; design addendum "PR 15" § H; prototype example 6).**

A "Being booked" item MUST be neutral, with the ordinary border and no red anywhere in the view. It MUST read "Being booked automatically." where a "Needs you" item puts its red sentence, and the kind's sentence under it, and MUST have no "What you can do". It MUST NOT count in the badge. The position's venue mark stays red meanwhile (see the venue mark requirement).

#### Scenario: Neutral and counted nowhere

- GIVEN one item in `being_booked`
- WHEN the page and the navigation render
- THEN the item says "Being booked automatically.", has no red border and no "What you can do", and no badge is drawn

### Requirement: The Booked-Automatically List Shows The Last 30 Days And A Booking Is Never Red

> **Added 2026-10-16 (owner decision 66, Q5 answered (a); design addendum "PR 15" § G and § H; prototype examples 7 and 11).**

"Booked automatically" MUST say "The last 30 days, newest first, at most 100." and list the route's `booked` as a table of neutral rows, one row group per exchange so the columns line up, with the headings "Booked (UTC)", "Pair", "Side", "Quantity", "Strategy", "Fills", "By" and "Now". "By" MUST read "automatically" for `decided_by` `automatic` and "by hand" for `owner` (a proposal approved before this unit was deployed). "Now" MUST read "waiting for the next comparison" while `discrepancy_open` is true and "the venue agrees again" once it is false. There is nothing to mark as seen. A booking is a result and MUST NEVER be red. On a phone the bookings MUST become cards.

#### Scenario: The rows and their columns

- GIVEN three bookings on bybit and one on binance
- WHEN the page renders
- THEN a table with the eight headings is drawn with a BYBIT group of three rows and a BINANCE group of one, newest first within each

#### Scenario: A hand booking says so

- GIVEN a booking whose `decided_by` is `owner`
- WHEN its row renders
- THEN "By" reads "by hand"

#### Scenario: A booking waiting for the scan

- GIVEN a booking whose `discrepancy_open` is true
- WHEN its row renders
- THEN "Now" reads "waiting for the next comparison"

#### Scenario: A booking is never red

- GIVEN any booking
- WHEN its classes are read
- THEN it uses no `loss` and no amber class

#### Scenario: A phone shows cards

- GIVEN a phone viewport
- WHEN the bookings render
- THEN each is a card and no table is drawn

### Requirement: The Bookings Feature Is Removed From The Panel

> **Added 2026-10-16 (owner decision 66, Q1 answered (a); design addendum "PR 15" § F and § H).**

Nothing in the panel MUST propose, approve or reject a booking. `features/bookings/` (`BookingsListView`, `BookingCard`, both dialogs, `usePendingBookings`, `format.ts`, `outcomeMessage.ts` and their tests), `features/positions/pendingProposal.ts`, `features/overview/DecisionRail.tsx` and its test, and the `BookingProposal` types the panel no longer reads MUST be removed, and nothing MUST import them. The keys `positions.venue.noProposal` and `positions.venue.line.noProposal` and the `overview.decisionRail.*` keys MUST be deleted from both locales.

#### Scenario: No source file reaches the removed code

- GIVEN the panel's sources
- WHEN every import and every string is searched
- THEN none names `usePendingBookings`, `BookingsListView`, `pendingProposalNames`, `DecisionRail` or `/reconciliation/bookings`

#### Scenario: No request for proposals

- GIVEN any page of the panel is rendered
- WHEN the network is read
- THEN no request is made to a booking route

#### Scenario: The removed keys are gone

- GIVEN both locale files
- WHEN their keys are read
- THEN `overview.decisionRail.*` and the two `noProposal` keys are absent

### Requirement: Every Discrepancies Text Exists In English And Spanish

> **Added 2026-10-16 (owner decision 66; the owner approved the prototype on 2026-10-16, "Esta muy bien", to be confirmed again on the implementation; design addendum "PR 15" § I).**

Every text above MUST be a key under `nav.discrepancies` or `discrepancies.*` in both `en.json` and `es.json`, and MUST NOT be hard-coded. The Spanish MUST be copied exactly from the approved prototype `visual/project/Discrepancies.html` (examples 10, 12 and 13, 15), including: the item "Discrepancias"; the title "Discrepancias"; the sections "Requiere su atención", "Registrándose" and "Registradas automáticamente"; "No se pudo registrar automáticamente."; "Se está registrando automáticamente."; "Nada requiere su atención. El exchange coincide con el libro mayor en cada comparación confirmada."; "Leyendo discrepancias…"; "La comparación con el exchange no se ejecuta en modo simulación, así que aquí no se verifica nada."; "Ningún registro en los últimos 30 días."; the "By" values "automáticamente" and "a mano"; the positions line "Ver la discrepancia". The plurals of the badge's name MUST exist as `_one` and `_other`. The word "booking" is "registro" in Spanish, as the panel's existing Spanish already says.

#### Scenario: Every key exists in both locales

- GIVEN every key the page, the navigation and the venue mark reference
- WHEN both locale files are read
- THEN each key exists in both and none is empty

#### Scenario: The Spanish reads as approved

- GIVEN the language is Spanish
- WHEN the page renders the states of examples 10 and 13
- THEN the texts equal the prototype's, character for character

#### Scenario: Numbers use the Spanish decimal comma

- GIVEN the language is Spanish and a net of 0.5 SOL
- WHEN the item renders
- THEN it reads 0,5 SOL

### Requirement: Red Appears In Three Places Of This Unit, Each With Its Words, And The Amber Allow-List Gains Nothing

> **Added 2026-10-16 (owner decision 66, Q7; design addendum "PR 15" § H; decision 65's rule that red says something is wrong and needs the owner, always with words).**

Red (`loss`) MUST appear in this unit only on a "Needs you" item, on the nav badge (its words are its accessible name) and on the venue mark of an open position (decision 65). A booking, a result, MUST never be red. `DecisionRail.tsx` MUST leave the list of files allowed to use amber (`AMBER_ALLOWED` in `panel-tokens.test.ts`) and nothing MUST join it. Styling MUST use palette tokens only: no hex and no `var()` inside a `className`, and no `style` prop in non-test source.

#### Scenario: The allow-list lost one entry and gained none

- GIVEN `panel-tokens.test.ts`
- WHEN its list of amber files is read
- THEN `DecisionRail.tsx` is absent and no new file is present

#### Scenario: No palette bypass in the new files

- GIVEN the new frontend files
- WHEN the theme test scans them
- THEN none has a hex colour, a `var()` in a `className` or a `style` prop

### Requirement: The Discrepancies View Is Operable By Keyboard And Named For Assistive Technology

> **Added 2026-10-16 (design addendum "PR 15" § H; prototype examples 1 to 3 and 11).**

The Discrepancies item MUST be reachable by keyboard like the other items. Each list MUST be a section named by its heading. Each item MUST be named by its pair, and each strategy name MUST be a real link. The read line's button MUST be a button named "Read again". The first-read failure MUST be `role="alert"` and the loading line `role="status"`.

#### Scenario: Lists are named by their headings

- GIVEN the page with items
- WHEN it is read by assistive technology
- THEN each list is a region named "Needs you", "Being booked" or "Booked automatically"

#### Scenario: The button is reachable

- GIVEN the read line
- WHEN the Tab key is pressed from the title
- THEN focus reaches the "Read again" button and Enter reads again
