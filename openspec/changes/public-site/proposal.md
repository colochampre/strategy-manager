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
  - **The VPS provider:** netcup GmbH, in a data centre in Nuremberg, Germany (owner, 2026-11-12). Germany is in the EU, which the AAIP lists as adequate.
- **Deletion today.**
  - There is no "delete my account".
  - The ledger cannot be deleted by design.
  - Cloudflare's own user records cannot be deleted (its seat-management page).

  What a user may ask for is the lawyer's question 3.

## Questions for a lawyer

The owner sends them in Spanish to a lawyer they know. This is the English summary.

1. Does the database need registering with the AAIP (art. 21 suggests it does), and through which procedure? What must the privacy policy state (Ley 25.326), and may the address be other than a home address?
2. International transfer: the data is stored on netcup's server in Nuremberg, Germany (EU, adequate), and sign-in and traffic pass through Cloudflare (United States). The United States is not an adequate country, so for Cloudflare express consent or model clauses are needed: is an express consent inside the acceptance checkbox enough? Does Cloudflare's standard data processing agreement serve?
3. The right to deletion against an append-only trading ledger and the absence of account deletion. Is anonymising enough?
4. Financial regulation: could the service count as investment advice or management, or as a virtual asset service provider (CNV)? Does a user's trading API key count as an "instrument that allows control" over virtual assets? If so, does the individuals' exemption under 35,000 UVA a month apply, and how is it measured for a service that moves no funds of its own? Does charging for plans change the answer?
5. Liability: consumer law applies while free (art. 1) and a clause limiting liability for damage is void (art. 37, Disposición 377/2026). The draft now answers for the service's own damage, leaves market risk to the user, and leaves the exchange and TradingView answering for their own services. Is that right? May the service be offered "as it is and as available"? (Reworded 2026-11-12.)
6. Users abroad: the draft no longer chooses a forum (CCyC arts. 1109 and 2654), disputes go to the user's domicile. Does that expose the service to foreign courts and consumer laws? Restrict to Argentina? (Reworded 2026-11-12.)
7. Minimum age.
8. Terms while it is free: a draft is published in the panel and binds by use. Is that enough while it is free? What is the exposure if someone loses money before they are reviewed? (Added 2026-11-12, reworded the same day.)
9. Acceptance: is a checkbox "I accept the terms and have read the privacy policy", recorded with the user, the version and the date, enough proof? Must it be asked again on every change? (Added 2026-11-12.)

### What public sources already say (researched 2026-11-12)

Not legal advice; primary texts where found, for the lawyer to confirm.

- **Consumer law applies while it is free.** Ley 24.240 art. 1 covers whoever acquires or uses services "en forma gratuita u onerosa" as final user. So questions 5 and 8 apply today, not only with paid plans.
- **Liability (question 5).** Art. 37 inc. a) holds as not agreed any clause that limits liability for damages, and the listing of abusive clauses (Res. 53/2003, updated by Disposición 377 of March 2026) names excluding or limiting the provider's liability for damage it causes. The draft's blanket exclusion of "failures of the app" is therefore likely void; the market risk of a trade is a different thing and can be stated as a risk.
- **Jurisdiction (question 6).** CCyC art. 2654 and art. 1109 (and Ley 24.240 art. 36): against a consumer, a choice-of-forum clause is not valid; the consumer's domicile governs. The draft's `[JURISDICTION]` placeholder should become "the courts of your domicile", or go.
- **International transfer (question 2).** The AAIP's adequacy list (Disp. 60/2016, Res. AAIP 34/2019) does not include the United States. A lawful transfer to a non-adequate country needs the data subject's express consent, or a contract on the model clauses (Disp. 60/2016, Res. AAIP 198/2023). That makes question 9's checkbox the natural place for an express consent to the transfer.
- **Registration (question 1).** Ley 25.326 art. 21: private databases whose use exceeds the purely personal must be registered with the AAIP; an unregistered one is unlawful.
- **CNV (question 4).** A PSAV is whoever, as a business, does one of five activities "para o en nombre de otra persona" (Ley 25.246 art. 4 bis, after Ley 27.739). The closest is "custodia y/o administración de Activos Virtuales o instrumentos que permitan el control sobre los mismos", and RG CNV 1058/2025 art. 8 limits that category to custodial services. The app holds no funds, but an API key that can trade is arguably an instrument of control. Individuals are exempt under 35,000 UVA a month (art. 1). This is the sharpest open question.
- **Acceptance (question 9).** CCyC art. 1106: an electronic medium satisfies the written form in consumer contracts; doctrine accepts a click as a declaration of will. The checkbox is a valid form; what it must show beforehand is the lawyer's call.

Sources: argentina.gob.ar (Ley 24.240, RG CNV 1058/2025, AAIP international transfers), marval.com, abogados.com.ar, aldiaargentina.microjuris.com, pensamientocivil.com.ar.

## The lawyer's answers (consultation, notes received 2026-11-19)

The owner's notes, taken during the consultation, verbatim:

> Evitar exponerse a la legislación de cada país. Cuanto menos exposición mejor. Evitar principalmente Estados Unidos y países que suelen evitar brindar servicios aplicaciones importantes (por algo será que algunos países se evitan).
>
> Titular de los datos
> Registrar la base de datos
>
> Normativa europea
> La información personal no se comparte con terceros
> Casilla de consentimiento sirve
>
> Pedir nombre, apellido, país y edad +18
> Pedir cuit si el usuario tiene mucho volumen. Segmentar los perfiles de usuario. Se podría exigir los datos cuando el usuario supera ciertos montos.
> Resoluciones de la UIF.
>
> Hay consumidor financiero.
> No tomar usuarios norteamericanos. Recomendado por ahora: limitar a solo Argentina
> Verificar en términos que la veracidad de sus datos es cierta.
> Derecho reservado a suspensión de cuenta si el usuario falsea datos.
>
> Dejar bien claro:
> Qué servicio da la app, en que condiciones, cómo, a qué te obligas, cómo recibe el servicio el usuario.
> Riesgos vinculados a estrategias de terceros.
>
> Conectar via api consultas.siaj.ar    config > api key > conector personalizado > mcp
> Normativa argentina con temas financieros y regulatoria
> Defensa consumidor, que busque aspectos de defensa respecto al caso de la app.
> regulaciones de uif
>
> Redactar bien especificado lo que se garantiza del funcionamiento de la app y responsabilidad ante fallos de la app, de tradingview o el Exchange vinculado. Responsabilidad de pérdidas ocasionadas por suscribirse a estrategias de terceros

The lawyer also set up SIAJ Consultas (`consultas.siaj.ar`), a search over Argentine legislation, and suggested connecting it as an MCP server. The owner connected it at user scope on 2026-11-19. Its key is personal and lives only in the owner's Claude configuration, never in this repository.

How the notes map onto the nine questions (the assistant's reading, for the owner to correct):

- **1 (registration, privacy policy):** "Titular de los datos", "Registrar la base de datos".
- **2 (international transfer):** "Normativa europea", "La información personal no se comparte con terceros", "Casilla de consentimiento sirve".
- **3 (deletion):** not in the notes. Anonymising is what the account-deletion change built.
- **4 (financial regulation):** "Resoluciones de la UIF", "Hay consumidor financiero", "Normativa argentina con temas financieros y regulatoria", "regulaciones de uif", and the CUIT above a volume.
- **5 (liability):** "Redactar bien especificado lo que se garantiza…", "Riesgos vinculados a estrategias de terceros".
- **6 (users abroad):** "No tomar usuarios norteamericanos. Recomendado por ahora: limitar a solo Argentina".
- **7 (minimum age):** "edad +18".
- **8 (terms while free):** "Dejar bien claro: Qué servicio da la app…".
- **9 (acceptance):** "Casilla de consentimiento sirve".
- **New, not asked:** asking for name, surname and country; the user vouching that their data is true; suspending an account whose data is false; segmenting profiles by volume.

### What SIAJ says on the notes (researched 2026-11-19)

Read through SIAJ by a research worker, for the lawyer to confirm; not legal advice. Unread parts are listed at the end.

- **PSAV.** RG CNV 1058/2025 art. 8 labels category 4 "Custodia y/o administración de Activos Virtuales o instrumentos que permitan el control sobre los mismos (siempre y cuando no sean no custodiados)", and its custody articles speak of private keys, wallets and segregated client assets. No sentence was found that places a non-custodial executor, trading through the user's own key, inside or outside it, and none on whether a perpetual contract is an "activo virtual". Natural persons may only do categories 1 and 2 (art. 8), and are exempt from registering while all their activity stays at or below 35,000 UVA per calendar month, valued at the last day's UVA (art. 1). Aiming at Argentine residents is itself a "punto de contacto" (art. 3).
  [RG 1058/2025](https://consultas.siaj.ar/ver/LEG%3Acnv%3ACNV-410635)
- **CNV advice and management.** An AAGI (asesoramiento, gestión de órdenes, administración de carteras) must be a company, and the figure is grounded in Ley 26.831's "valores negociables". Whether these perpetuals are valores negociables was not answered. [Normas CNV Tít. VII Cap. IV](https://consultas.siaj.ar/ver/LEG%3Acnv%3ACNV-NT-T07-C04)
- **UIF.** Res. UIF 49/2024 binds PSAVs registered with the CNV. For every natural-person client, at onboarding and regardless of volume (art. 23): full name, document, nationality, date and place of birth, CUIL/CUIT, real address, phone and e-mail, occupation, PEP and sanctions checks; biometrics for remote onboarding (art. 22). Volume only grades the client's risk (arts. 26-29), and fixed amounts appear only in reporting (art. 39, 6 SMVM a month). So "pedir CUIT si el usuario tiene mucho volumen" does not match that scheme: if the app were a sujeto obligado, the CUIT would be asked of everyone. [Res. UIF 49/2024](https://consultas.siaj.ar/ver/LEG%3Auif%3AUIF-397597)
- **Consumer law.** Ley 24.240 art. 4 (clear, detailed information on the service and its conditions) and art. 37 a) (a clause limiting liability for damage is held not agreed). Disposición 954/2025 replaced Res. 316/2018 and 424/2020: a service contracted at a distance shows, in plain sight and at first access, a link to cancel it with no prior sign-in (art. 4), and the "botón de arrepentimiento". [Ley 24.240](https://consultas.siaj.ar/ver/LEG%3Anacion%3A638), [Disp. 954/2025](https://consultas.siaj.ar/ver/LEG%3Anacion%3A417152)
- **Personal data.** Ley 25.326 art. 6 lists what the user is told before collection (purpose and recipients, the file and its owner's identity and address, mandatory or optional answers, consequences, the rights of access, rectification and deletion). Art. 21 registration names private databases "destinado a proporcionar informes"; whether this one is caught, and the AAIP's current procedure, were not settled. [Ley 25.326](https://consultas.siaj.ar/ver/LEG%3Anacion%3A64790)
- **Argentina only, 18+.** Nothing read forbids refusing foreign residents or requires 18+; both are choices the norms allow.
- **Not read or not found:** RG 1058 past art. 16; RG CNV 994/2024; Ley 25.246 art. 20 itself; Ley 26.831 art. 2; Disposición 377/2026 (not found in SIAJ); "consumidor financiero"; the AAIP's current registration rule.

## Out of scope

- The paid plans themselves, and the seat-priority requirement (multi-user `tasks.md`, under G.D.5).
- A "delete my account" feature. It may follow from question 3, as its own change. *Delivered as its own change (`account-deletion`, PR #118, 2026-11-19).*
