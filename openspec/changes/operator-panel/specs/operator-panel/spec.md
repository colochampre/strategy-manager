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
> asks for served by the server and two information buttons), a "Saved" text
> after a save, two Copy buttons, the full webhook URL with its host, and a win
> rate in "By pair". Fifteen requirements are added after "Copy-Ready Webhook
> Message, Secret Revealed Only On Explicit Request"; "Strategy Detail Shows
> Stats, Uptime, and Lifecycle Controls" and that webhook requirement each gain
> one sentence pointing to them, and "Every Panel String Is Localized EN/ES"
> gains one scenario.

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
enable/disable and archive controls. It also carries the delete control of
"Deleting A Strategy Requires Explicit Confirmation And States Its Refusal"
(added 2026-10-02, owner decision 42). It also lists the strategy's closed
operations, as the six requirements that follow this one describe (added
2026-10-04, owner decision 43). Its settings column MUST carry the share of the
pool per trade, and its stats by pair MUST include a win rate, as the
requirements added for unit 12f describe (unit 12f, 2026-10-06, owner decisions
44 and 48).

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
explicit "Show secret" action, and neither requests the secret.)

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
validation or refusal text; and the Save button with the "Saved" text beside it.
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
| The validation text, a refused save, the unreadable stored value, "Saved" | Always visible |
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

After a save of the share and after a save of the allowed pairs, the control
MUST show "Saved" / "Guardado" beside its button. It MUST be announced to a
screen reader as a polite status: its live region MUST be in the document before
it has anything to say, empty until then. There MUST be NO timer: it stays until
the owner changes something in that control again.

| Control | "Saved" appears | "Saved" goes |
| --- | --- | --- |
| The share | When the PATCH answers 200 with a strategy | At the next movement of the handle, activation of a stop, or keystroke in the field; and when the page is left |
| The allowed pairs | When the PUT answers 200 and the list on screen is the saved one | At the next pair added or removed; and when the page is left. Typing in the search box changes no pair and leaves it. |

A failed save MUST show its refusal and NEVER "Saved"; the two MUST NEVER be on
screen together, and a new save MUST clear "Saved" before it is sent. If the
re-read of the allowed pairs after a 200 fails, so that the list on screen is the
old one, "Saved" MUST NOT be shown.

#### Scenario: "Saved" shows after the share is saved

- GIVEN the owner saved a share of `33.5` and the API answered 200 with a strategy
- WHEN the control is read
- THEN "Saved" shows beside Save

#### Scenario: "Saved" goes at the next change of the share

- GIVEN "Saved" shows after a share save
- WHEN the owner moves the handle, activates a stop, or types a character, each tried in turn
- THEN "Saved" is gone each time

#### Scenario: "Saved" stays until something changes

- GIVEN "Saved" shows after a share save
- WHEN ten minutes pass with no change
- THEN "Saved" still shows

#### Scenario: "Saved" shows after the allowed pairs are saved

- GIVEN strategy S1 on pool `(bybit, usdt-m, USDT)` had allowed pairs `{ETHUSDT}`, the owner added `SOLUSDT` and the PUT answered 200
- WHEN the pairs control is read
- THEN "Saved" shows beside its button, and goes when a pair is added or removed again

#### Scenario: Typing in the pair search does not remove "Saved"

- GIVEN "Saved" shows after a pairs save
- WHEN the owner types `SOL` in the pair search box without adding or removing a pair
- THEN "Saved" still shows

#### Scenario: A refused save never shows "Saved"

- GIVEN the owner saved a share and the API answered 409, or 500
- WHEN the control is read
- THEN the refusal shows and "Saved" does not

#### Scenario: A new save clears "Saved" before it is sent

- GIVEN "Saved" shows after a share save, and the owner changes the value and presses Save again
- WHEN the second request is in flight
- THEN "Saved" is not shown

#### Scenario: The live region exists before it speaks

- GIVEN the share control and the pairs control render with nothing saved
- WHEN the document is read
- THEN each has a polite status region that is empty

#### Scenario: A failed re-read after a successful pairs save shows no "Saved"

- GIVEN the PUT of the allowed pairs answered 200 and the re-read of the list then fails, so the old list is on screen
- WHEN the pairs control is read
- THEN "Saved" does not show

### Requirement: The Webhook Block Has Two Copy Buttons

> **Added 2026-10-06 (owner decisions 44 (12f.5) and 48, answered 2026-10-06; design addendum "unit 12f" § E).** "Copied" / "Copiado" are the owner's own words.

The webhook block MUST offer two buttons: "Copy URL" / "Copiar URL" beside "Show
secret", and "Copy message" / "Copiar mensaje" under the alert message. Each MUST
write to the clipboard exactly the text on screen: the URL's, the placeholder
while the secret is hidden and the real URL, secret included and as shown, once
it is revealed; the message's, the message shown. Copying MUST NEVER request the
secret, and MUST NOT turn the hidden placeholder into the revealed secret. The
panel MUST NOT claim to clear the clipboard when the secret is hidden or the view
is left. The URL MUST be text, never a link, and MUST NEVER be requested.

After a copy the panel MUST show:

| Result | Text beside the button activated | Until |
| --- | --- | --- |
| The alert message was copied | "Copied" / "Copiado" | Something else is copied, or the block is closed |
| The URL was copied | "Copied" / "Copiado" | The same, AND the URL on screen stops being the one that was copied |
| The browser refused, or has no clipboard | "Could not copy. Select the text and copy it by hand." / "No se pudo copiar. Seleccione el texto y cópielo a mano." instead of "Copied" | As the row of the button it belongs to |

"Copied" beside the URL MUST be shown only while the URL on screen is the one
copied. Showing or hiding the secret MUST remove it for good, so it does not
return when the secret is shown or hidden again; and a host that arrives after
the copy, which changes the URL on screen, MUST remove it too. The message's
"Copied" MUST NOT be touched by showing or hiding the secret. Only one "Copied"
MUST be on screen: a copy with the other button moves it. The panel MUST NOT
keep the copied text; it MAY keep only which button was used, whether it worked
and the state of the URL it copied.

#### Scenario: Copying the URL with the secret hidden copies the placeholder

- GIVEN strategy S1's webhook block is open, the secret is hidden and the webhook's host is `https://example.duckdns.org`
- WHEN the owner activates "Copy URL"
- THEN the clipboard holds the URL as shown, `https://example.duckdns.org/webhook/tradingview?secret=` followed by the placeholder, "Copied" shows beside the button, and no request for the secret was made

#### Scenario: Copying the URL with the secret revealed copies the real URL

- GIVEN the owner pressed "Show secret" and the real URL is on screen
- WHEN the owner activates "Copy URL"
- THEN the clipboard holds exactly the URL on screen, and "Copied" shows beside the button

#### Scenario: Showing the secret removes "Copied" beside the URL

- GIVEN the owner copied the URL with the placeholder and "Copied" shows
- WHEN the owner presses "Show secret"
- THEN "Copied" is gone, and the clipboard still holds the placeholder URL

#### Scenario: Showing the secret again does not bring "Copied" back

- GIVEN the owner copied the placeholder URL, pressed "Show secret" and then "Hide secret"
- WHEN the URL on screen is the placeholder again
- THEN "Copied" is not shown, because the URL on screen was not copied since

#### Scenario: Hiding the secret removes "Copied" beside the URL

- GIVEN the owner revealed the secret, copied the URL and "Copied" shows
- WHEN the owner presses "Hide secret"
- THEN "Copied" is gone

#### Scenario: A host that arrives after the copy removes "Copied"

- GIVEN the webhook's host is still loading, the owner copied the URL as the path alone and "Copied" shows
- WHEN the host arrives and the URL on screen gains it
- THEN "Copied" is gone

#### Scenario: The message's "Copied" survives showing and hiding the secret

- GIVEN the owner copied the alert message and "Copied" shows beside "Copy message"
- WHEN the owner presses "Show secret" and then "Hide secret"
- THEN "Copied" still shows beside "Copy message"

#### Scenario: A copy with the other button moves "Copied"

- GIVEN "Copied" shows beside "Copy message"
- WHEN the owner activates "Copy URL"
- THEN "Copied" shows beside "Copy URL" only

#### Scenario: A refused copy says so and never shows "Copied"

- GIVEN the browser refuses the clipboard write
- WHEN the owner activates "Copy URL"
- THEN "Could not copy. Select the text and copy it by hand." shows, "Copied" does not, and nothing is written to the console

#### Scenario: A browser with no clipboard says so

- GIVEN the panel is opened where no clipboard is available
- WHEN the owner activates "Copy message"
- THEN "Could not copy. Select the text and copy it by hand." shows

#### Scenario: Neither Copy button requests the secret

- GIVEN the secret is hidden
- WHEN the owner activates "Copy URL" and "Copy message" and the requests are counted
- THEN no request to `GET /api/webhook-secret` was made

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

- While the host is loading, the path alone MUST be shown, and that is what a
  copy takes.
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
- THEN the path alone shows, and a copy at that moment takes the path alone

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

### Requirement: Settings Manages One Key Per Exchange

> **Revised 2026-09-24 (owner decision 18).** READ and TRADE slots are
> withdrawn; each exchange has one key.
>
> **Revised 2026-09-25 (owner decision 20).** A DEGRADED exchange (an enabled
> pool with no key) is distinguished from an exchange that was never
> configured, both shown as "no key" but only the DEGRADED case marked.

The Settings view MUST show one entry per exchange, showing last-4, whether
the key reads and trades or reads only, and the recorded facts when a key is
active, and MUST allow adding or replacing that exchange's key. An exchange
whose key cannot trade MUST be marked read-only and MUST state that, with dry
run off, its opening signals are refused until a key that can trade futures is
stored. An exchange with an enabled pool and no key at all MUST be marked "no
key" and MUST state that, with dry run off, its opening signals are refused
until a key is stored.

A fact the owner confirmed MUST NOT be presented as verified. It MUST be shown
as "trade not verified" or "withdraw not verified", each with the date the owner
confirmed it, in a neutral tone (the mark is state, not a call to action). A
row sealed before facts were recorded MUST be shown as "not validated" together
with both marks.

#### Scenario: An exchange with no key shows a defined empty state

- GIVEN no active credential exists for Binance and its pool is not enabled
- WHEN Settings renders
- THEN Binance's entry shows a defined empty state and an add control, not last-4 or permissions

#### Scenario: An active key shows last-4 and recorded facts only

- GIVEN an active credential exists for Bybit
- WHEN Settings renders
- THEN Bybit's entry shows only its last-4, its trade capability, the date its live read passed and its internal-transfer state, never a full key, a secret or a raw permission payload

#### Scenario: An owner-confirmed key is never shown as verified

- GIVEN Binance's active credential was saved with the owner's two confirmations
- WHEN Settings renders
- THEN Binance's entry shows "trade not verified" and "withdraw not verified", each with the date the owner confirmed it, and does not state that the key has no withdrawal permission as a fact

#### Scenario: A key sealed before facts were recorded is shown as not validated

- GIVEN Binance's active credential was sealed before facts were recorded
- WHEN Settings renders
- THEN Binance's entry shows "not validated" together with both "not verified" marks, and no confirmation date

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
owner: success with the resulting last-4 and recorded facts (with the read-only
warning when the key cannot trade), or the specific refusal reason (live read
failed, venue unreachable, withdraw permission present, permissions unavailable,
a required owner confirmation missing, a confirmation that does not apply, or a
concurrent save).

For Binance the form MUST ask for two owner confirmations, "withdrawals
disabled" and "Enable Futures", each unticked by default, and MUST NOT allow
submitting until both are ticked. The server enforces the same rule. For Bybit
the form MUST show no confirmation.

#### Scenario: A refused save shows its reason

- GIVEN the owner submits a key with withdraw permission
- WHEN the save is refused
- THEN the panel shows the withdraw-permission refusal reason and stores nothing

#### Scenario: A successful save shows the resulting last-4 and facts

- GIVEN the owner submits a valid key that can trade futures
- WHEN the save succeeds
- THEN the panel shows the resulting last-4 and recorded facts for that exchange, with no read-only warning

#### Scenario: A read-only key is saved with a warning

- GIVEN the owner submits a valid key that cannot trade
- WHEN the save succeeds
- THEN the panel shows the resulting last-4 together with the read-only warning, and the exchange is marked read-only

#### Scenario: A Binance key cannot be submitted without both confirmations

- GIVEN the owner has typed a Binance key and ticked at most one of the two confirmations
- WHEN the form is shown
- THEN submitting is disabled, and both confirmations are cleared together with the key fields once the submission finishes

#### Scenario: A refusal for a missing confirmation names it

- GIVEN the server refuses a Binance save because a confirmation is missing
- WHEN the refusal is shown
- THEN the panel names which confirmation is missing and stores nothing

#### Scenario: A Bybit form shows no confirmation

- GIVEN the owner opens the key form for Bybit
- WHEN the form renders
- THEN it shows no owner confirmation, because Bybit's facts are verified by the venue

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

#### Scenario: The operations table, dialog and fills are localized, with LONG and SHORT unchanged

> **Added 2026-10-04 (owner decisions 43 and 44).**

- GIVEN the locale is Spanish and a closed trades table, a rehearsal row's dialog and its fills table are on screen
- WHEN every visible string is read
- THEN the column headings, tags, sentences, dialog labels, fills labels and states are Spanish and sourced from i18n, and the operation's side reads "LONG" or "SHORT"

#### Scenario: The share control, "Saved", the Copy buttons and the win rate are localized

> **Added 2026-10-06 (owner decisions 44 and 48, design addendum "unit 12f").**

- GIVEN the locale is Spanish and a strategy detail view shows the share control with both information buttons open, a "Saved" text, the webhook block with both Copy buttons and a "By pair" table
- WHEN every visible string is read
- THEN each is the Spanish text of "The Detail Page's Follow-Up Texts Are Exactly These, In English And Spanish", sourced from i18n, with no leftover English

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
