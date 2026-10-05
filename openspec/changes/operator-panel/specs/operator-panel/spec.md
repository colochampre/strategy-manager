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
2026-10-04, owner decision 43).

(Previously: no mention of the operations list, which the requirements below
now specify.)

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
fees are incomplete shows an asterisk right after its PnL figure, explained by one note under the table's title that appears only when a row of the page on screen has incomplete fees (owner decision 46, 2026-10-05); the words stay in the detail dialog. A figure served as
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

Under the table's title the panel MUST show a sentence for each of the
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
