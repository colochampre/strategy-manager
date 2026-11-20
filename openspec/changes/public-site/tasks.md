# Tasks: Public site

The plan is in `proposal.md`. Each task records its evidence when done. Push, PR and merge happen only on the owner's word.

**On standby (owner, 2026-11-12)**, except PS.0: the site, Google and the paid plans wait for the lawyer's and an accountant's answers. The owner's words: "Bueno, todo esto queda en standby. Es complejo, tengo que hacer esas consultas y me hacen plantearme si vale la pena".

**Resumed 2026-11-19** after the lawyer's consultation (owner: "Después vamos con lo que me dijo el abogado en la consulta"). The notes are in `proposal.md`, verbatim. The branch was rebuilt as `feat/public-site-v2` from `main` at `60315d2`: its 10 own commits were cherry-picked, and the 15 others, docs that had reached `main` another way, were left behind. `feat/public-site` is kept, untouched, as it was.

**Age by declaration, no full KYC (owner, 2026-11-19):** "Dale, con la declaración por ahora. Pedir KYC completo no me parece buena idea. La app debe ser de simple acceso y uso. Si el usuario de entrada ve que se pidan cosas como fotos de su dni y lo típico de un exchange importante, probablemente no lo haga."

- [ ] PS.0 The privacy policy inside the panel, now (owner, 2026-11-12: "Dale, arrancá con el borrador dentro del panel"). Sign-up is open, so whoever signs in is told what is stored when it is stored (Ley 25.326 art. 6).
  - `/privacy` in the shell, EN and ES, written from the inventory in `proposal.md`; a link at the foot of every page; a notice on the first visit that links it, dismissed per browser and per policy version (`PRIVACY_VERSION`), not a record of consent.
  - Placeholders the owner fills before the panel moves: `[FULL NAME]`, `[ADDRESS]`, `[DATE]`, `[LOG RETENTION]`, `[BACKUP RETENTION]`, `[HOW TRADE RECORDS ARE HANDLED ON DELETION]`, and their Spanish twins. The last one waits for the lawyer (question 3). Every panel deploy (pps.6) from now on refuses a bundle that still holds `[FULL NAME]` or `[NOMBRE COMPLETO]`.
  - It carries the control authority's notice of Disposición DNPDP 10/2008, in Spanish as written and in English as a translation, for the lawyer to confirm.
  - *Built 2026-11-12, not yet read by the owner:* `features/privacy/PrivacyPage.tsx` and `PrivacyNotice.tsx`, the route, and the shell's notice and footer link. Strict TDD, RED on assertions (no heading, no region, no link). 15 hand mutations, all killed. Frontend gate green: `npm run lint`, and `npx vitest run` with 146 files and 3811 tests.
  - *Reviewed by the owner 2026-11-12 ("Lo revisé, y esta todo ok"), then reshaped* from Hyperliquid's policy as a reference for sections and format, and the owner's "Yo le agregaría justificacion al texto":
    - twelve sections, adding cookies and browser storage, minimum age (18) and contact; extra lines for the legal basis (art. 5), identity checks on requests, no perfect security, third-party links, and "if you do not agree, do not use the app";
    - every request goes to `privacy@strategymanager.trade` (`PRIVACY_CONTACT`), which Cloudflare Email Routing forwards to the owner, so the personal address leaves the page;
    - the name and address come from the build, `VITE_PRIVACY_OWNER_NAME` and `VITE_PRIVACY_OWNER_ADDRESS`, set in the untracked `frontend/.env.production.local` (owner, "Dale, si"). Without them the page shows `[FULL NAME]`/`[ADDRESS]` (`[NOMBRE COMPLETO]`/`[DOMICILIO]`). pps.6 builds from a clean worktree, so the deploy copies that file into the worktree before `npm run build`;
    - centred title and date, uppercase section titles, text justified from `sm` up; `PRIVACY_VERSION` bumped to `2026-11-12-draft-2`, so the notice shows again.
    - Strict TDD, RED on assertions (5 failed: sections, contact, name from the build, layout, Spanish). 7 hand mutations, all killed. Frontend gate green: `npm run lint`, and `npx vitest run` with 146 files and 3815 tests.
  - *Email Routing set up by the owner 2026-11-12:* Cloudflare's three MX records (`route1`..`route3.mx.cloudflare.net`) and its SPF and DKIM TXT records on `strategymanager.trade`; a rule sends `privacy@` to the owner's verified address, catch-all off. A test message arrived; the first one went to spam and was marked not spam. It only receives: replying as `privacy@` needs an SMTP relay and Gmail's "Send as", still to do.
  - *The notice closes by itself on `/privacy`* (owner, 2026-11-12: "al ir a la pagina /privacy el aviso podría cerrarse automaticamente"): opening the policy counts as reading this version. RED on an assertion (the notice was found). The mutant that keeps the version unstored is killed; the one that drops the render guard survives in jsdom, where the effect runs before the assertion, and the guard is kept because in a browser it stops the notice being painted for one frame.

- [ ] PS.1 Confirm the data inventory's open items, without printing an address, e-mail or credential:
  - what the API's access log records as the client address behind the tunnel;
  - journald retention on the VPS;
  - backup retention under `/var/backups/strategy-manager`;
  - ~~the VPS provider and its country~~: netcup GmbH, Nuremberg, Germany (owner, 2026-11-12: "el VPS está hosteado en Nuremberg. Es un servicio de Netcup"). Written into the privacy policy (`others.server`, test pinned, RED on an assertion), `PRIVACY_VERSION` bumped to `2026-11-12-draft-3`, and into the lawyer questions.
- [ ] PS.2 Drafts of the privacy policy and the terms of service, in English and Spanish, written from `proposal.md`'s inventory and nothing else.
  - Placeholders: `[FULL NAME]` and `[ADDRESS]`.
  - The owner and their lawyer review them; the lawyer's answers and every change are recorded here.
  - *Terms built inside the panel 2026-11-12, not yet read by the owner* (owner: "Hagamos los terminos directamente", instead of closing sign-up to a list of e-mails until terms exist). `/terms` in the shell, EN and ES, linked from the footer beside privacy. Fifteen sections: who provides it, what it does (holds no funds, simulation or live), not financial advice, risks (all the capital can be lost), account and keys, strategies you publish, acceptable use, availability, liability, price (free today), stopping, privacy (links the policy), changes, governing law (Argentina), contact (`privacy@strategymanager.trade`).
    - Placeholders: `[DATE]` and its Spanish twin; the name and address come from the build, as in the policy.
    - *Corrected 2026-11-12 from the research in `proposal.md`* (owner: "Dale, corregilas ya en el borrador, y si hay que cambiar o agregar preguntas del artefacto, hacelo también"): liability no longer excludes the app's own failures, which consumer law would void; it answers for the service's own damage and states market risk as the user's. Governing law names Ley 24.240 and sends disputes to the courts of the user's domicile, instead of a `[JURISDICTION]`. A test pins both and that neither placeholder is left; RED on an assertion. Lawyer questions 1, 2, 4, 5, 6 and 8 reworded with what the sources say, in the artifact and here.
    - The privacy policy and the terms share `shared/legal/LegalDocument.tsx`; the placeholders for name and address moved to `legal.placeholder`.
    - Today the terms bind by use ("By signing in and using the app you accept them"). A recorded acceptance (a checkbox, stored with the user, the version and the date, asked again on a change) is not built: it stores something new, so it also changes the policy, and whether it is enough is question 9.
    - Strict TDD, RED on assertions (8 failed: no heading, no text, no link, no footer link). The privacy tests stayed green through the extraction. 7 hand mutations, all killed. Frontend gate green: `npm run lint`, and `npx vitest run` with 147 files and 3823 tests.
- [ ] PS.3 The home page, in English and Spanish: what the app does and does not do (it holds no funds; trading can lose money; it is not financial advice), a link to the panel to sign in, and links to privacy and terms.
- [ ] PS.4 The site in `site/`:
  - plain HTML and CSS, no build step and no external script;
  - a `_headers` file with a CSP;
  - a language switch;
  - how `[FULL NAME]` and `[ADDRESS]` reach the page (the repository is public).

  A test reads every page and refuses one that does not link privacy and terms, or a placeholder left in a published build.
- [ ] PS.5 Owner-run: the Pages project serves `site/` at `about.strategymanager.trade`. Check that the Access application on `strategymanager.trade` does not cover that name (a private window opens the page with no sign-in).
- [ ] PS.6 Owner-run: verify `strategymanager.trade` in Google Search Console with a DNS TXT record in Cloudflare.
- [ ] PS.7 Owner-run: complete Google's branding page and publish the OAuth app. Record exactly what Google asks for, above all about `cloudflareaccess.com`.
  - Home page, privacy and terms links.
  - Authorized domains `strategymanager.trade` and `cloudflareaccess.com`.
  - No logo.
- [ ] PS.8 Owner-run: tick Google in the Access application's login methods. Sign in by Google with an address that is not one of Google's test users; `check_users.sh` shows its row.
- [ ] PS.D Delivery: the PR (owner's word), Pages deploy, and the delivery log of this change.

## From the lawyer's answers (specs written 2026-11-19)

Written from the lawyer's notes in `proposal.md`, quoted verbatim where they set a rule, and the owner's decisions above. Owner, 2026-11-19: "Dale, armá las especificaciones, ni bien tenga las respuestas del abogado te las paso y completamos". Items marked **open** wait for the lawyer's follow-up (LQ1-LQ5 below); everything else is decided.

**Risk:** item 1 (a migration and new personal data), item 2 (a gate in front of the API) and item 3 (every user, the four existing ones included, meets a new step). An independent verifier runs on the backend unit, and the migration is rehearsed on a throwaway restore.

### Specs

- **LS1 Who may use the app.** Adults resident in Argentina only. The lawyer: "No tomar usuarios norteamericanos. Recomendado por ahora: limitar a solo Argentina" and "Pedir nombre, apellido, país y edad +18". Age is declared, not proven (owner: "Dale, con la declaración por ahora"). No full KYC: no document photo, selfie, address, date of birth or occupation (owner: "Pedir KYC completo no me parece buena idea. La app debe ser de simple acceso y uso").
- **LS2 The sign-up step.** A signed-in user whose profile is not complete sees one form before anything else, and nothing else of the panel until it is done. It asks:
  - first name and last name, both required;
  - CUIT (or CUIL), required, its check digit validated as it is typed (LD1, owner 2026-11-19: "Dale, CUIT obligatorio en el alta");
  - country of residence. Only Argentina is accepted; any other answer says the service is offered only to residents of Argentina for now, and stores nothing;
  - "I declare that I am 18 or older";
  - "I declare that the data I give is true" (the lawyer: "Verificar en términos que la veracidad de sus datos es cierta");
  - "I accept the terms of service and have read the privacy policy", both linked, with the express consent to the international transfer of the data (Cloudflare, United States) written into it (the lawyer: "Casilla de consentimiento sirve").

  Every box must be ticked; none is pre-ticked. The four existing users meet the same form on their next visit.
- **LS3 What is stored.** On the user: first name, last name, CUIT, country (`AR`), and when the two declarations were made. The acceptance is recorded apart, one row per acceptance: user, the terms version, the privacy version and the time, never updated or deleted. First and last name and the CUIT are seen only by the user and the admin. The public display name stays separate and optional.
- **LS4 The gate holds on the server too.** Until the profile is complete, the API refuses (409 `PROFILE_INCOMPLETE`) every request that stores or trades for the user: saving a key, a pool, a subscription, a strategy, a mode change. It keeps answering what lets the user get out: reading their own data, "Close now", leaving a subscription and deleting the account. The panel's form is not the only guard.
- **LS5 Account deletion and the identity.** The owner's purpose for the CUIT, "por lo menos tener el resgistro de movimientos del usuario si alguna autoridad llegara a pedirlos", conflicts with today's deletion, which leaves the trades under nobody's name. The drafts (PS.11, PS.12) therefore propose: deletion still erases the e-mail, the display name and the keys, but keeps the first name, last name and CUIT beside the ledger for a term (**open, LQ6**), seen by nobody but the admin answering an authority, and erases them after it. `DeleteAccount` and the users CHECK of migration 0045 change to match once the lawyer answers. The acceptance rows stay, like the ledger. This also covers the account-deletion change's T4 for the policy text (LS7).
- **LS6 Asked again on a change.** When the terms or the privacy version changes, the user ticks the acceptance box again before continuing (LS2's last box only). **Open (LQ3):** whether every change asks again, or only a material one.
- **LS7 The privacy policy follows.** It names the new data (first and last name, country, the declarations and the acceptance record) and why they are asked. It names the express consent to the transfer, and the "delete account" button with what it keeps (account-deletion T4). `PRIVACY_VERSION` is bumped. The project rule in CLAUDE.md asks for this in the same PR as LS3.
- **LS8 The terms, rewritten.** The lawyer: "Dejar bien claro: Qué servicio da la app, en que condiciones, cómo, a qué te obligas, cómo recibe el servicio el usuario. Riesgos vinculados a estrategias de terceros." and "Redactar bien especificado lo que se garantiza del funcionamiento de la app y responsabilidad ante fallos de la app, de tradingview o el Exchange vinculado. Responsabilidad de pérdidas ocasionadas por suscribirse a estrategias de terceros". So the terms state:
  - what the service is and how the user receives it: orders placed on their own exchange account through their own key, signals from TradingView, no custody;
  - who it is for: adults resident in Argentina (LS1);
  - what the provider commits to and what it does not guarantee;
  - liability for the app's own failures, kept as consumer law allows (Ley 24.240 art. 37);
  - TradingView's and the exchange's failures, which are those services' own;
  - the risks of subscribing to a strategy someone else authors, and who answers for its losses;
  - the user's duty to give true data, and "Derecho reservado a suspensión de cuenta si el usuario falsea datos".

  `TERMS_VERSION` is introduced, bumped on each change, and recorded with every acceptance (LS3).
- **LS9 Suspension.** The terms reserve the right (LS8). **Open (decision, not the lawyer's):** whether the admin can suspend an account from `/users` now, and what a suspended account may still do. The proposal: no new openings or subscriptions, while closing, leaving and deleting still work, as LS4.
- **LS10 Owner-run: register the database with the AAIP** (the lawyer: "Registrar la base de datos"). **Open (LQ4):** the current procedure.

### Questions back to the lawyer (LQ)

- **LQ1 PSAV.** Is a service that holds no funds and trades through the user's own exchange key, with no withdraw permission, a PSAV (Ley 25.246 art. 4 bis, RG CNV 1058/2025 category 4, "...instrumentos que permitan el control sobre los mismos (siempre y cuando no sean no custodiados)")? Are USDT-margined perpetuals "activos virtuales" or "valores negociables"? Every user has already passed full KYC at their exchange (Binance and Bybit require it for futures).
- ~~**LQ2 CUIT and volume.**~~ Answered by the owner, 2026-11-19, not sent: "Los volumenes o montos no los determinó él. Habría que armar algo nosotros mismos, según cómo convenga hacerlo, o como dijiste antes, exigir el cuit en cualquier caso. El propósito es por lo menos tener el resgistro de movimientos del usuario si alguna autoridad llegara a pedirlos. Que la herramienta no sea una facilitadora de lavado de dinero". Now an owner decision, **LD1**: the CUIT always at sign-up, or only above an amount this project sets.
- **LQ3 Asking again.** Must the acceptance be asked again on every change of the terms or the policy, or only on a material one?
- **LQ4 AAIP.** Does art. 21 ("...privado destinado a proporcionar informes") reach this database, and which procedure applies today?
- **LQ6 Identity after deletion.** May the first name, last name and CUIT be kept after the user deletes their account, beside the trade records, so that an authority's request can still be answered, and for how long? Res. UIF 49/2024 art. 17 keeps records ten years for sujetos obligados.
- ~~**LQ5 "Normativa europea".**~~ Answered by the owner, 2026-11-19, not sent: "al referirnos a normativa europea, se mencionaba que al ser distintas normativas y tener distintas reglas, lo mejor era evitar exponerse a ellas, como precaucion. Jurisdicciones extraterritoriales, riesgos regulatorios internacionales, etc. Cosas que no pretendo que me alcancen como persona respondable de la app." It supports LS1 (Argentina only) and asks nothing more of the consent box.

### Tasks

- [ ] PS.9 LS2-LS5 backend: the profile fields and the acceptance rows (migration 0046), `PUT /api/me/profile`, the server gate, and the deletion wiping the new fields. Route: inline; independent verifier after.
  - *Started 2026-11-19* (owner: "Dale, si por favor"). Work units: PS.9a the CUIT check digit and the profile's rules (domain); PS.9b migration 0046, the model and the repository; PS.9c `PUT /api/me/profile`, `POST /api/me/acceptance` and the new `GET /api/me` fields; PS.9d the gate (409 `PROFILE_INCOMPLETE`) and the route walk that pins it; PS.9e the deletion wiping the new fields.
  - Decisions taken here, for the owner to overrule: the profile is set once, a correction goes through the contact address (the CUIT's purpose is a stable record); the current terms and privacy versions live in the backend and `GET /api/me` publishes them, so the panel and the server cannot disagree; until LQ6 is answered the deletion erases the identity too, as the published policy says today. LS1's "no CUIT" predates LD1 and was removed.
  - *Built 2026-11-19, PS.9a-PS.9e*, strict TDD, every RED on an assertion first (`DID NOT RAISE`, `404 == 422`, the route walk naming the first ungated route):
    - `identity/domain/profile.py`: the CUIT's check digit (remainder 1 has no digit, so no such CUIT exists), names, Argentina checked first; `identity/domain/legal.py`: the versions in force (`2026-11-19-draft-1` terms, `2026-11-19-draft-4` privacy) and `profile_status`.
    - Migration 0046: six nullable columns on `users`, whole or absent (`ck_users_profile_whole`), `ck_users_cuit_shape`, `ck_users_country_served`, `ck_users_deleted_names_nobody` now also requiring no identity; `legal_acceptances`, append-only by the ledger's two triggers. Its downgrade refuses while an acceptance is recorded. 22 scenarios on real PostgreSQL.
    - `PUT /api/me/profile` (422 `COUNTRY_NOT_SERVED`, `PROFILE_INVALID` with the field, `DECLARATION_MISSING` with the box; 409 `LEGAL_VERSION_CHANGED` naming the versions in force, `PROFILE_ALREADY_GIVEN`), `POST /api/me/acceptance` (409 `PROFILE_INCOMPLETE` without a profile), and `GET /api/me` with `profile`, `profile_status` (`MISSING`, `ACCEPTANCE_OUTDATED`, `COMPLETE`) and `legal_versions`.
    - The gate, `require_complete_profile`: 409 `PROFILE_INCOMPLETE` on saving a key, creating or changing a strategy (allowed pairs, webhook secret, invite codes included), subscribing or changing a share, and a mode change. Open to a user who has not signed up: reading, removing a key, Close now, leaving, archiving or deleting a strategy, revoking a code, the code lookup, the display name, the form, the box, deleting the account. `test_every_api_route_is_guarded` pins both lists against the app's routes; proven non-vacuous by disabling the gate (two tests red).
    - Deletion erases the identity and keeps the acceptance rows (proven by leaving the CUIT in the wipe: red).
    - The router tests about something else waive the gate explicitly (`tests.identity_auth.waive_profile_gate`; `act_as` and `without_a_database` stand for a user already signed up).
    - Gate: ruff, mypy (410 files), full backend suite exit 0.
  - *Independent verifier, 2026-11-20* (commits `5224e3c`, `bfa4765` against `4089c61`): no blockers. LS2, LS4, LS6 met on the server; LS3 and LS5 partly, by the recorded deferrals. Its probes: a concurrent second PUT waited on the first and got 409 with no acceptance; string or numeric unticks refused; non-ASCII digits refused; a version bump closed and reopened the gate; deletion with and without a profile both 204. Advisories kept for later: **deploying this backend before PS.10's form locks every existing user out of every gated write** (ship them together); the API takes the ISO code `AR`; a deletion committed between sign-in and the profile UPDATE can answer 500; `User` and `Profile` reprs carry the identity; a LIVE user with no profile cannot change mode until signed up. One test docstring claimed more ways out than it exercised; corrected.
  - Not done here: the admin's `/users` view of the identity (LS3 says the admin sees it); the worker still executes signals for a subscriber who has not signed up (LS4 asks the API only).
- [ ] PS.10 LS2, LS6 frontend: the sign-up form as the panel's first and only screen until done; the re-acceptance box on a version change.
- [ ] PS.11 LS7 privacy policy text, EN and ES, with `PRIVACY_VERSION` bumped.
  - *Drafted 2026-11-19 for the lawyer's review* (owner: "Hacemos la nueva versión de términos y política de privacidad para que de paso las revise junto con las preguntas?"): the identity and the acceptance record under what is stored; what the identity is for and that it is required (art. 6 c, d); the admin's view; authorities only on a lawful request; the express consent to the transfer abroad; the identity kept after deletion for `[RETENTION AFTER DELETION]` / `[PLAZO DE CONSERVACIÓN]` (LQ6); the deletion button; asked again on a change. `PRIVACY_VERSION` is `2026-11-19-draft-4`.
  - Strict TDD: 4 tests RED on assertions first. Still open there: `[DATE]`, the log and backup retention (PS.1), LQ6's term.
- [ ] PS.12 LS8 terms text, EN and ES, and `TERMS_VERSION`. It waits on LQ1 only where the text depends on it.
  - *Drafted 2026-11-19 with PS.11.* Nineteen sections; new ones: who may use it, what we commit to (and what is not guaranteed), what you commit to, strategies by other users, records and authorities, stopping and suspension. Liability now separates the app's own failures (with an example), market risk, TradingView's and the exchange's. "As it is and as available" is gone. Acceptance is by the sign-up box, asked again on a change.
  - Strict TDD: 6 tests RED on assertions first (the section list, eligibility, commitments, third-party strategies, the three failures, records and the deletion button). `TERMS_VERSION` comes with the acceptance record (PS.9, PS.10).
- [ ] PS.13 LS9 suspension, once decided.
- [ ] PS.14 LS10 owner-run AAIP registration, once LQ4 is answered.
