# Delta for Signal Ingress

> **Added 2026-10-05 (follow-ups 9qf.1 and 9qf.5 of PR 12g; no owner decision was
> needed).**
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
> **This delta holds** the requirement of 9qf.1 (a number that is not finite) and
> the two of 9qf.5 (a number the database would refuse, and a body that is not
> an alert object).
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
