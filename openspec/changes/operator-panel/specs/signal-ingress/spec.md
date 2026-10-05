# Delta for Signal Ingress

> **Added 2026-10-05 (follow-up 9qf.1 of PR 12g; no owner decision was needed).**
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
> **No requirement of the main spec is revised.** The requirement below is
> ADDED. It applies to every pool: the refusal happens before the alert is
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
