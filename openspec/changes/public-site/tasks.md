# Tasks: Public site

The plan is in `proposal.md`. Each task records its evidence when done. Push, PR and merge happen only on the owner's word.

**On standby (owner, 2026-11-12)**, except PS.0: the site, Google and the paid plans wait for the lawyer's and an accountant's answers. The owner's words: "Bueno, todo esto queda en standby. Es complejo, tengo que hacer esas consultas y me hacen plantearme si vale la pena".

- [ ] PS.0 The privacy policy inside the panel, now (owner, 2026-11-12: "Dale, arrancá con el borrador dentro del panel"). Sign-up is open, so whoever signs in is told what is stored when it is stored (Ley 25.326 art. 6).
  - `/privacy` in the shell, EN and ES, written from the inventory in `proposal.md`; a link at the foot of every page; a notice on the first visit that links it, dismissed per browser and per policy version (`PRIVACY_VERSION`), not a record of consent.
  - Placeholders the owner fills before the panel moves: `[FULL NAME]`, `[ADDRESS]`, `[DATE]`, `[SERVER PROVIDER]`, `[SERVER COUNTRY]`, `[LOG RETENTION]`, `[BACKUP RETENTION]`, `[HOW TRADE RECORDS ARE HANDLED ON DELETION]`, and their Spanish twins. The last one waits for the lawyer (question 3). Every panel deploy (pps.6) from now on refuses a bundle that still holds `[FULL NAME]` or `[NOMBRE COMPLETO]`.
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
  - the VPS provider and its country (owner).
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
