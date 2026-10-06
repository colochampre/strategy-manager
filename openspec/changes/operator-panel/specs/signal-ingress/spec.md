# Delta for Signal Ingress

> **Added 2026-10-05 (follow-ups 9qf.1, 9qf.5 and 9qf.6 of PR 12g; no owner
> decision was needed).**
>
> This delta extends `openspec/specs/signal-ingress/spec.md`. This change touches
> that spec because building decision 45 showed that the webhook accepted an
> alert whose price was not a finite number: the alert parser converted each
> numeric string with `Decimal`, which accepts `NaN` and every spelling of
> infinity without raising, and tested nothing for finiteness.
>
> What that did before this delta, observed on the route against a database
> migrated to `head`:
>
> - `NaN` in `price`, `data.contracts` or `data.position_size`: the webhook
>   answered 200 and stored a signal and a job. The CHECK `price > 0` does not
>   exclude it, because PostgreSQL orders `NaN` above every number. In the worker
>   an opening order then failed at build and its job was retried until its
>   attempts ran out.
> - An infinity in any of the three: an unhandled 500, because the column's range
>   refuses it and nothing caught that.
>
> The same defect class had three more members, found while building 9qf.5 and
> each an unhandled 500 before it: a price of zero or below (the CHECK refuses
> it), a number with more integer digits than `NUMERIC(38, 18)` holds, and a
> request body that is not valid JSON or not a JSON object.
>
> Before 9qf.6 only the non-finite refusal and an unknown strategy wrote a log
> line; every other refusal of a malformed alert answered 422 and left no trace,
> and TradingView shows the response of a webhook to nobody.
>
> The last known 500 on the path, found by 9qf.5 and closed by 9qf.7
> (2026-10-06), is a body the alert parser accepts and the database cannot
> STORE: a NUL character or a lone surrogate in any string or object key of the
> body, a number JSON cannot hold (`NaN`, an infinity, or `1e999`) in a part of
> the body the alert parser does not read, and a body nested so deeply that the
> JSON parser's recursion overflows (between 2,000 and 3,000 levels on the
> route). Each answered an unhandled 500.
>
> One more member was left open by 9qf.7 and decided by the owner on
> 2026-10-06 (decision 47, task 9qf.8): nothing in the application bounded the
> size of a body. `request.json()` read it whole and a body with an 8 MB string
> was stored with a 200. The whole body is kept for good in
> `signals.raw_payload` and is read back by every query that selects it, so the
> webhook now refuses a body larger than 65,536 bytes with a 413.
>
> **This delta holds** the requirement of 9qf.1 (a number that is not finite),
> the two of 9qf.5 (a number the database would refuse, and a body that is not
> an alert object), the one of 9qf.6 (every refusal of a malformed alert
> leaves exactly one warning that carries no value the sender supplied), the
> one of 9qf.7 (a body that cannot be stored) and the one of 9qf.8 (a body larger
> than 64 KiB).
>
> **No requirement of the main spec is revised.** The requirements below are
> ADDED. They apply to every pool: each refusal happens before the alert is
> routed to a strategy, so no settlement-currency pool is read, reserved or
> written.

## ADDED Requirements

### Requirement: A Number That Is Not Finite Is Refused At The Webhook

The system MUST refuse an authenticated alert in which any numeric field,
`price`, `data.contracts` or `data.position_size`, is not a finite number: `NaN`,
a signalling `NaN` or an infinity of either sign, in any spelling the decimal
parser accepts. The refusal MUST be a 422 that names the field and MUST NOT
repeat the value received. The system MUST NOT persist the signal and MUST NOT
enqueue a job. The system MUST write exactly one warning that names the field
and carries no payload, no price and no secret, because TradingView shows the
response of a webhook to nobody.

A finite number MUST be accepted exactly as before.

This requirement does not change the database: the CHECK on `signals.price`
still does not exclude `NaN`. A signal stored with a `NaN` price before this
requirement is neither read nor rewritten by it.

#### Scenario: NaN in the price is refused and nothing is stored

- GIVEN an authenticated alert that is valid except that its `price` is `"NaN"`
- WHEN the webhook is received
- THEN the response is a 422 whose detail names `price` and does not contain the value, no signal row and no job exist afterwards, and one warning names `price`

#### Scenario: Every numeric field is checked

- GIVEN an authenticated alert that is valid except that `data.contracts`, or `data.position_size`, is `"NaN"`
- WHEN the webhook is received
- THEN the response is a 422 that names that field and nothing is stored

#### Scenario: An infinity is refused as a bad request, not as a server error

- GIVEN an authenticated alert that is valid except that one numeric field is `"Infinity"` or `"-Infinity"`
- WHEN the webhook is received
- THEN the response is a 422 that names the field, never a 500, and nothing is stored

#### Scenario: Every spelling the parser accepts is refused

- GIVEN the spellings `NaN`, `nan`, `sNaN`, `Infinity`, `-Infinity`, `+Infinity`, `inf` and `Inf`
- WHEN each is parsed as any of the three numeric fields
- THEN each is refused

#### Scenario: A finite number is accepted as before

- GIVEN an authenticated alert whose numeric fields are all finite
- WHEN the webhook is received
- THEN it is accepted, stored and enqueued exactly as before this requirement

### Requirement: A Number The Database Would Refuse Is Refused At The Webhook

The system MUST refuse an authenticated alert whose `price` is not above zero,
and an authenticated alert in which `price`, `data.contracts` or
`data.position_size` has more integer digits than the column holds. The
`signals` table declares those three columns as `NUMERIC(38, 18)`, which holds
20 digits before the point, and puts one sign rule on them: the CHECK `price >
0`. The test is made on the number as the column would store it, rounded to 18
decimals, so a price that rounds to zero and a value that rounds up past the
last integer digit are refused too. Each refusal MUST be a 422 that names the
field and MUST NOT repeat the value received, MUST NOT persist the signal and
MUST NOT enqueue a job, and MUST write exactly one warning that names the field
and carries no payload, no value and no secret.

The system MUST NOT impose a sign rule on `data.contracts` or
`data.position_size`, because the database has none: a closing alert carries a
`position_size` of zero and a short position may carry a negative one. Each
accepts any finite number that fits the column.

Before this requirement each refusal was made by the database at the insert,
nothing caught it and the webhook answered an unhandled 500.

#### Scenario: A price of zero or below is refused and nothing is stored

- GIVEN an authenticated alert that is valid except that its `price` is `"0"` or `"-1"`
- WHEN the webhook is received
- THEN the response is a 422 whose detail names `price` and does not contain the value, no signal row and no job exist afterwards, and one warning names `price`

#### Scenario: A price that rounds to zero is refused

- GIVEN an authenticated alert whose `price` is above zero but smaller than the column's last decimal, `"0.0000000000000000001"`
- WHEN the webhook is received
- THEN it is refused exactly like a price of zero

#### Scenario: Contracts and position size accept zero and a negative number

- GIVEN an authenticated alert that is valid except that `data.contracts`, or `data.position_size`, is `"0"` or `"-1"`
- WHEN the webhook is received
- THEN it is accepted, stored and enqueued

#### Scenario: A number too large for the column is refused as a bad request

- GIVEN an authenticated alert that is valid except that one numeric field has 21 integer digits, such as `"100000000000000000000"` or `"1E+20"`
- WHEN the webhook is received
- THEN the response is a 422 that names the field, never a 500, nothing is stored, and one warning names the field

#### Scenario: A number whose exponent the column cannot encode is refused

- GIVEN an authenticated alert that is valid except that `data.contracts`, or `data.position_size`, is `"0E+999999"` or `"1E-20000"`
- WHEN the webhook is received
- THEN the response is a 422 that names the field, never a 500, and nothing is stored, because PostgreSQL's `NUMERIC` cannot receive a display scale above 16383 and a zero is no exception

#### Scenario: The largest number the column holds is accepted

- GIVEN an authenticated alert whose `price` is `"99999999999999999999"`
- WHEN the webhook is received
- THEN it is accepted, stored and enqueued

### Requirement: A Request Body That Is Not An Alert Object Is Refused At The Webhook

The system MUST refuse an authenticated request whose body is not valid JSON, and
one whose body is valid JSON but not an object: a list, a string, a number, a
boolean or `null`. Each refusal MUST be a 422, MUST NOT persist a signal or
enqueue a job, and MUST write exactly one warning that carries no part of the
body. Before this requirement each answered an unhandled 500.

#### Scenario: A body that is not valid JSON is refused

- GIVEN an authenticated request whose body is not valid JSON
- WHEN the webhook is received
- THEN the response is a 422, nothing is stored, and one warning says the body is not valid JSON without repeating any of it

#### Scenario: A JSON body that is not an object is refused

- GIVEN an authenticated request whose body is `[]`, `"alert"`, `5` or `null`
- WHEN the webhook is received
- THEN the response is a 422, nothing is stored, and one warning says the body is not a JSON object without repeating any of it

### Requirement: A Body The Database Cannot Store Is Refused At The Webhook

The system MUST refuse an authenticated alert whose body cannot be stored as
received, whatever its shape. The whole body is persisted verbatim in
`signals.raw_payload` (`jsonb`), and `symbol`, `action` and `signal_type` are
`text`. A body MUST be refused when it carries: a NUL character, or a lone
surrogate, in any string of the body or in any object key, at any depth; a
number that is not finite, `NaN`, an infinity or a float that overflowed such as
`1e999`, anywhere in the body; or a nesting of more than 64 levels, counting the
body as level 1 and its `data` object as level 2. The depth bound leaves generous
room above the alert's contract and sits far below every depth at which a layer
was observed to fail. A body nested at the bound MUST be accepted and one level
past it MUST be refused.

Each refusal MUST be a 422 that names `body`, MUST NOT repeat any key or value
the sender supplied, MUST NOT persist the signal and MUST NOT enqueue a job, and
MUST write exactly one warning, `webhook alert refused: body <reason>`, that
carries no key and no value. A body nested so deeply that the JSON parser itself
overflows its recursion MUST be refused the same way: the route catches that one
exception type where it parses the body.

The check MUST be one iterative pass over the parsed body, covering object keys
as well as values, because a recursive walk would raise the very `RecursionError`
it removes. It MUST live in the domain beside the other refusals, so nothing can
store a body that skipped it. The refusals that already existed keep their
reasons; this check runs after them.

A valid alert MUST be unaffected: one that carries `signal_param` as the string
`"{}"`, non-ASCII text, an extra unknown key, a literal backslash followed by
`u0000` (text, not a NUL), or a finite number of any magnitude is accepted,
stored unchanged and enqueued, and its idempotency key does not change. The
accepted path gains no query and no lock.

Before this requirement each refusal was made by PostgreSQL at the insert, or by
the encoding of the idempotency key, nothing caught it and the webhook answered
an unhandled 500. This requirement does not bound the size of the body; the
requirement "A Body Larger Than 64 KiB Is Refused At The Webhook" does.

#### Scenario: A NUL character anywhere in the body is refused

- GIVEN an authenticated alert that is valid except that a NUL character (`\u0000`) is in `data.action`, `symbol`, `time`, `signal_param`, an extra key, a value nested in an object or an array, or an object key
- WHEN the webhook is received
- THEN the response is a 422 that names `body` and does not contain the character, no signal row and no job exist afterwards, and one warning reads `webhook alert refused: body contains a character that cannot be stored`

#### Scenario: A lone surrogate is refused like a NUL

- GIVEN an authenticated alert that is valid except that a lone surrogate (`\ud800`) is in one of the same places
- WHEN the webhook is received
- THEN it is refused exactly like a NUL character

#### Scenario: A number JSON cannot hold is refused

- GIVEN an authenticated alert that is valid except that an extra key holds `NaN`, `Infinity`, `-Infinity` or `1e999`, alone, in an array or in a nested object
- WHEN the webhook is received
- THEN the response is a 422 that names `body`, nothing is stored, and one warning reads `webhook alert refused: body contains a number that is not finite`

#### Scenario: A body at the depth bound is accepted and one level past it is refused

- GIVEN an authenticated alert with an extra key nested so that the body is 64 levels deep, as arrays or as objects
- WHEN the webhook is received
- THEN it is accepted, stored and enqueued
- AND GIVEN the same alert nested one level deeper, the response is a 422, nothing is stored, and one warning reads `webhook alert refused: body is nested too deeply`

#### Scenario: A body deeper than the JSON parser can read is refused

- GIVEN an authenticated request whose body is a valid alert with an extra key nested 10,000 levels deep (a body nested 100,000 levels is over 64 KiB and is refused as too large, below, before it is parsed)
- WHEN the webhook is received
- THEN the response is a 422, never a 500, nothing is stored, and one warning reads `webhook alert refused: body is nested too deeply`

#### Scenario: A valid alert is accepted unchanged

- GIVEN an authenticated alert with `signal_param` `"{}"`, non-ASCII text and an extra unknown key
- WHEN the webhook is received
- THEN it is accepted, stored with the body exactly as received, enqueued, and keeps the idempotency key it always had

### Requirement: A Body Larger Than 64 KiB Is Refused At The Webhook

The system MUST refuse an authenticated request whose body is larger than 65,536
bytes. A body of exactly 65,536 bytes is within the limit. The refusal MUST be a
413 whose detail is a fixed text and echoes nothing the sender supplied, MUST NOT
persist a signal or enqueue a job, and MUST write exactly one warning,
`webhook alert refused: body is larger than 65536 bytes`, that carries no part of
the body and no value the sender wrote, the declared `Content-Length` included. A
real alert is about 300 bytes; the limit bounds what is kept for good in
`signals.raw_payload`. It is enforced in the application, not at the edge, so it
does not depend on how a tunnel or proxy in front of it is configured. It applies
to this endpoint only.

The body MUST NOT be read whole and then measured. A declared `Content-Length`
past the limit MUST be refused before any of the body is read. A body with no
declared length MUST stop being read at the first chunk that takes the count of
bytes received past the limit. The count of bytes actually received is the
authority: a `Content-Length` that is absent, is not a number or is smaller than
what arrives MUST NOT let a larger body through and MUST NOT raise, and a body
within the limit MUST be accepted whatever the header says.

Authentication MUST stay first: a request that fails it MUST be answered 401
without any of its body being read, whatever length it declares or sends, and
writes no line. A body within the limit MUST be parsed exactly as before, so a
body that is not valid JSON, is not an object, or is nested so deeply that the
JSON parser overflows its recursion answers the 422 it always answered. An
accepted alert MUST be unaffected: the same response, the same stored row and
the same idempotency key, with no added query and no lock.

Before this requirement a body of any size was read whole and stored with a 200.

#### Scenario: A body one byte past the limit is refused and nothing is stored

- GIVEN an authenticated, otherwise valid alert of 65,537 bytes with its `Content-Length`
- WHEN the webhook is received
- THEN the response is a 413 with the fixed detail, no signal row and no job exist afterwards, and one warning reads `webhook alert refused: body is larger than 65536 bytes`

#### Scenario: A body of exactly the limit is accepted

- GIVEN an authenticated, valid alert of exactly 65,536 bytes
- WHEN the webhook is received
- THEN it is accepted, stored with the body exactly as received and enqueued, and writes no warning

#### Scenario: A declared length past the limit is refused before the body is read

- GIVEN an authenticated request that declares a `Content-Length` past the limit
- WHEN the webhook is received
- THEN the response is a 413 and none of the body was read

#### Scenario: A body with no declared length stops being read at the limit

- GIVEN an authenticated request sent in chunks with no `Content-Length`, whose body is far larger than the limit
- WHEN the webhook is received
- THEN the response is a 413, nothing is stored, and reading stopped at the first chunk that took the count past the limit, not at the end of the body

#### Scenario: A header that does not tell the truth lets nothing through

- GIVEN an authenticated request whose body is past the limit and whose `Content-Length` is smaller than the body, zero, negative, empty or not a number
- WHEN the webhook is received
- THEN the response is a 413, never a 500, and nothing is stored
- AND GIVEN the same header on a body within the limit, it is accepted

#### Scenario: The refusal repeats nothing the sender wrote

- GIVEN an authenticated request whose oversized body carries a distinctive marker and whose `Content-Length` is a distinctive number
- WHEN the webhook is received
- THEN neither the marker nor the number appears in the response or in any log record

#### Scenario: An unauthenticated request is never read

- GIVEN a request with a wrong or missing secret whose body is past the limit, with or without a declared length
- WHEN the webhook is received
- THEN the response is a 401, none of the body was read, and the webhook writes no log line

### Requirement: Every Refusal Of A Malformed Alert Leaves Exactly One Warning

The system MUST write exactly one warning for each authenticated alert it
refuses as malformed, because TradingView shows the response of a webhook to
nobody. The warning MUST name the reason and, where there is one, the field. It
covers: a body that is not valid JSON or not an object; a missing `data` object;
a missing required field; a number that is not a string; a string that is not a
decimal; a number that is not finite, not above zero where it must be, or out of
range for the column; a body the database cannot store (9qf.7); a body larger
than 64 KiB (9qf.8); an empty or non-string `action`, `symbol`, `signal_type` or
`time`; a `signal_type` that is not a UUID; and a missing idempotency key. An
alert for an unknown strategy keeps the one warning it already had; no refusal
is logged twice.

The warning MUST NOT carry the payload, a price, a quantity, the secret or any
value the sender supplied. In particular the detail of the 422 for a string that
is not a decimal repeats the value received and MUST NOT reach the log: the log
text is the field and a fixed reason, and the detail of the response is
unchanged.

The system MUST NOT write a line for a request that fails authentication, and
MUST NOT write a warning for an accepted alert or a duplicate one: the endpoint
faces the internet and a line per unauthenticated request would be written for
every scan.

#### Scenario: A refused alert leaves one warning naming the field and the reason

- GIVEN an authenticated alert that is valid except that `price` is `"abc"`
- WHEN the webhook is received
- THEN the response is a 422 and exactly one warning reads `webhook alert refused: price is not a valid decimal string`

#### Scenario: A missing field leaves one warning

- GIVEN an authenticated alert with no `symbol`
- WHEN the webhook is received
- THEN exactly one warning reads `webhook alert refused: symbol is missing`

#### Scenario: The warning never carries what the sender supplied

- GIVEN an authenticated alert whose `price` is a distinctive marker string that is not a decimal
- WHEN the webhook is received
- THEN the 422 detail may repeat the marker, and no log record contains it

#### Scenario: An accepted alert and a duplicate write no warning

- GIVEN an authenticated valid alert, received twice
- WHEN the webhook is received each time
- THEN the first is accepted and the second is a duplicate, and neither writes a warning

#### Scenario: An unauthenticated request writes no line

- GIVEN a request with a wrong secret
- WHEN the webhook is received
- THEN the response is a 401 and the webhook writes no log line at all
