# Tasks: Public site

The plan is in `proposal.md`. Each task records its evidence when done. Push, PR and merge happen only on the owner's word.

- [ ] PS.1 Confirm the data inventory's open items, without printing an address, e-mail or credential:
  - what the API's access log records as the client address behind the tunnel;
  - journald retention on the VPS;
  - backup retention under `/var/backups/strategy-manager`;
  - the VPS provider and its country (owner).
- [ ] PS.2 Drafts of the privacy policy and the terms of service, in English and Spanish, written from `proposal.md`'s inventory and nothing else.
  - Placeholders: `[FULL NAME]` and `[ADDRESS]`.
  - The owner and their lawyer review them; the lawyer's answers and every change are recorded here.
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
