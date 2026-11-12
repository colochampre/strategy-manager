# Proposal: Public site (home, privacy, terms)

PLAN, 2026-11-12. Base `main` at `635a821`.

## Why

- **Google sign-in waits on it.** It became secondary at G.D.5 (multi-user `tasks.md`). Its OAuth app is still in Testing, and Google publishes an external app only with three things:
  - a home page on a verified domain the owner holds, which describes the app and is not only a login;
  - a privacy policy and terms of service;
  - every domain of the project registered under Authorized domains.

  Source: https://support.google.com/cloud/answer/15549049, read 2026-11-12.
- **The privacy policy is owed anyway.** Sign-up has been open since 2026-11-12 and a first real user signed up, so real people's data is stored today. The paid plans will need terms too.
- The owner's words (2026-11-12): "Si recomendas Google de todos modos, mientras esperamos la operación de STX, vayamos viendo de armar lo de Google. Lo veo más complejo lo de hacerlo ver por un abogado, pero a lo mejor consigo a algun conocido que me haga el favor."

## Settled

- **The privacy policy goes first, inside the panel** (owner, 2026-11-12). It needs neither the site, Google nor the paid plans, and sign-up is already open. The public site serves it again later, for Google.
- **Where the site lives.** A static site on Cloudflare Pages at `about.strategymanager.trade`, outside Access. It touches neither the API, the panel nor the Access application. The assistant proposed it and the owner did not object.
- **Who is responsible.** The owner, as a person, in Argentina, with contact `colochampre3@gmail.com`.
  - The full name and the address are placeholders, `[FULL NAME]` and `[ADDRESS]`, filled by the owner. Ley 25.326 art. 6 asks for both, so neither may be invented.
  - The repository is public, so how they reach the page is decided at PS.4: committed, or filled at publish.
- **Languages.** English and Spanish.
- **No logo.** An uploaded logo sends the app to Google's verification.
- **The Google client's domain.** `cloudflareaccess.com` sits under Authorized domains. Google accepted it without asking for proof of ownership (seen 2026-11-12). It is not on the Public Suffix List, so for Google it is Cloudflare's domain. Whether publishing asks to verify it is known only at publish (PS.7). If it does, this route to Google sign-in closes, and the pages still serve the open sign-up and the paid plans.

## What the app holds about a user (read from the code at `635a821`)

The privacy policy describes exactly this, no more. Items marked *to confirm* are PS.1.

- **Identity (`users`).**
  - The e-mail Access verified, and `created_at` / `last_seen_at`.
  - The mode (simulation or live).
  - An optional display name. It is public once set: Explore shows it beside the author's strategies.
  - No password: sign-in is Cloudflare Access's.
- **Exchange keys (`exchange_credentials`).**
  - API key and secret, envelope-encrypted. Only the worker decrypts them, at signing time, and the panel shows the last four characters.
  - Whether the key can trade (read from the venue, or confirmed by the user) and whether it could withdraw. A key that can withdraw is refused.
- **Balances.** The user's pools (`capital_pools`) and the balances read from their exchange account (`pool_balance_snapshots`).
- **Strategies the user authors.** Name, description, pairs, visibility, a share-link token and invite codes (only their hash). The webhook secret is stored as a hash.
  - A PUBLIC strategy shows its name, description, the author's display name and its record built from the author's real fills.
- **Subscriptions.** Strategy, share of the pool, leverage, status and dates. Each failed invite-code attempt is recorded too (user and time).
- **Trading records.** Every signal delivered to the user, reservation, order attempt and fill: price, quantity, fees and result. The ledger is append-only (CLAUDE.md rule 6): nothing in it is ever deleted.
- **Logs** (journald on the VPS). They carry user and strategy ids and order details, but no e-mail, key, secret or token (project rules).
  - *To confirm:* what the API's access log records as the client address behind the tunnel.
  - *To confirm:* how long journald keeps lines.
- **Backups.** Database dumps on the VPS under `/var/backups/strategy-manager`. *To confirm:* how long they are kept.
- **Not collected.** Passwords, payment data (no plan is paid yet), identity documents.
- **Who else handles it.**
  - **Cloudflare:** Access sign-in (e-mail, sign-in time, IP), the tunnel, DNS and Pages.
  - **Google:** only for a user who signs in with Google, once enabled.
  - **The exchanges** (Binance, Bybit): the user's own account, through the key the user gave.
  - **TradingView:** sends an author's alerts and receives nothing of a subscriber.
  - **The VPS provider:** *to confirm* its name and country.
- **Deletion today.**
  - There is no "delete my account".
  - The ledger cannot be deleted by design.
  - Cloudflare's own user records cannot be deleted (its seat-management page).

  What a user may ask for is the lawyer's question 3.

## Questions for a lawyer

The owner sends them in Spanish to a lawyer they know. This is the English summary.

1. Does the database need registering with the AAIP? What must the privacy policy state (Ley 25.326), and may the address be other than a home address?
2. International transfer: the data passes through Cloudflare (United States), and the VPS is in another country.
3. The right to deletion against an append-only trading ledger and the absence of account deletion. Is anonymising enough?
4. Financial regulation: could the service count as investment advice or management, or as a virtual asset service provider (CNV)? Does charging for plans change the answer?
5. Liability for losses, app failures or exchange failures: what the terms may limit, and what consumer law (Ley 24.240) forbids excluding once plans are paid.
6. Users abroad: restrict to Argentina, or state the governing law and jurisdiction?
7. Minimum age.
8. Terms while it is free: sign-up is open and free and no terms are published yet, only the privacy policy in the panel. Are terms needed now, without charging? What is the exposure if someone loses money before they exist? (Added 2026-11-12.)
9. Acceptance: is a checkbox "I accept the terms and have read the privacy policy", recorded with the user, the version and the date, enough proof? Must it be asked again on every change? (Added 2026-11-12.)

## Out of scope

- The paid plans themselves, and the seat-priority requirement (multi-user `tasks.md`, under G.D.5).
- A "delete my account" feature. It may follow from question 3, as its own change.
