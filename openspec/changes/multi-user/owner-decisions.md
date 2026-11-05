# Owner decisions for multi-user (binding once taken, not reopened)

Opened 2026-10-21. Design phase only: no code until the decisions below are taken and a proposal and a design exist. Operator-panel's decision 4 already set this apart: "Serving other users and charging them fees is a separate, large change, and may be a regulated activity (CNV)."

## The owner's request (verbatim, 2026-10-21)

1. "Te comento porqué quería eliminar la clave de Pionex y Bybit: Quería verificar si la app detecta que si tengo una clave de Binance, solo me ofrece agregar una de Bybit. Y si tengo una de cada una, ya no me deja agregar más. Si por ejemplo yo tengo dos cuentas distintas en Binance, y quisiera agregar la API key de esa cuenta secundaria, no podría. Además, con esa cuenta secundaria, yo quisiera poder tener estrategias propias, o sumarla a una existente, como las 3 activas actuales. Asi una estrategia podría hacer uso de más de una API key para abrir operaciones. Entiendo que para esto conviene mantener la restricción de una API key por Exchange por usuario, y si quisiera hacer uso de una cuenta secundaria, armar el sistema multi-user."

2. "Quiero que otro usuario pueda usar el sistema sin necesidad de pasarme sus API keys para que yo las agregue. Que sea auto gestionado. El usuario se loguea, configura su/s API key/s y 'copia' una o varias de las estrategias disponibles. Tendría su propio resumen de la evolucion de su cartera y su propio rendimiento por estrategia. Las vista Discrepancies solo las vería yo, como admin."

3. "El sistema de dry run tendría que aplicar a cada usuario individualmente. Si el usuario quisiera quedarse en modo simulación, y eventualmente pasarse al modo Live, tiene que poder hacerlo. Se me ocurre que hacer cliqueable el elemento 'DRY RUN/LIVE' con una confirmación, podría reemplazar tener que hacerlo desde el servidor, desde el .env"

4. "Dale, registralo y armamos el diseño. Te agrego una cosa antes de arrancar: Tema webhook, si un usuario quisiera, debe poder crear estrategias propias (todas públicas), con sus webhook y ser el responsable de esa estrategia, asi como hoy yo soy el que gestiona las tres existentes. Osea, un usuario sin conocimientos en tradingview, puede usar el sistema mediante suscripciones a otras estrategias, y otro usuario que sabe, tiene además la opción de gestionar sus propias estrategias."

## Already settled by the request

These come from the owner's own words above. They are not asked again.

- **R1. One API key per exchange per user.** The rule of today, now per user. A second account on the same exchange belongs to another user.
- **R2. Self-service.** A user signs in and stores their own keys. Nobody hands keys to the admin.
- **R3. Copying strategies.** A user subscribes to one or more of the available strategies. A signal of the strategy then trades on every subscriber's account, with each subscriber's own key.
- **R4. Per-user views.** Each user has their own portfolio summary and their own performance per strategy.
- **R5. Discrepancies is admin-only.**
- **R6. Simulation per user.** Each user is in simulation or live on their own, and can move from one to the other. The owner proposes a clickable `DRY RUN` / `LIVE` badge with a confirmation, instead of the server's `.env`.
- **R7. Users can author strategies.** Any user may create their own strategies, each with its own webhook, and is responsible for them. Every strategy is public. A user who knows nothing of TradingView only subscribes; one who does may also author.

## Open questions (asked one at a time, in this order; all answered on 2026-10-21, see Decisions)

- Q1. How a user is identified: the e-mail Cloudflare Access already verifies, or a login of the app's own.
- Q2. Who may become a user: invited by the admin only, or anyone who signs up.
- Q3. A subscription's size: a share of the subscriber's pool set by the subscriber, as a strategy's share is today, or something else.
- Q4. Joining and leaving a strategy with a position open: whether a new subscriber waits for the next opening signal, and what happens to an open position when a subscriber leaves.
- Q5. An author who disables or archives a strategy that has subscribers with open positions.
- Q6. Moving to live: what the confirmation requires (for example a trade-capable key stored first), and whether going back to simulation is refused while live positions are open.
- Q7. Whether the server's `DRY_RUN` stays as a global override that keeps everyone in simulation regardless of each user's choice.
- Q8. What the admin sees of other users (their positions, their keys' state, their performance) besides Discrepancies.
- Q9. What an author sees of their subscribers, and whether a new author's strategy is open to subscribers at once (decision 2 admits anyone).
- Q10. The existing data: the owner becomes the first user and admin, and today's three strategies and their history become theirs.
- Q11. Monetization: designed now, or left out of this change.

## Decisions

1. **A user is the e-mail Cloudflare Access verifies (Q1, 2026-10-21).** The owner chose "Email de Cloudflare Access" after asking whether each user would need a Cloudflare account ("cada usuario tendría que tener un usuario registrado en Cloudflare? O podría usar, por ejemplo, Google o su mail ingresado manualmente?").
   - No user needs a Cloudflare account. Access offers the methods the admin enables: a one-time PIN sent to any e-mail (today's method) and identity providers such as Google. Both can be on at once.
   - The app reads the e-mail from the Access token, which the tunnel already validates. It adds a users table and an admin role, and stores no password.
   - The free Zero Trust plan covers up to 50 users.
   - The cost is a dependency on Cloudflare for sign-in: leaving Cloudflare would mean building a login of the app's own.

2. **Anyone who signs in becomes a user, with no approval (Q2, 2026-10-21).** The owner's words: "Como probablemente hagamos el sistema de suscripción para las estrategias existentes, optaría por dejar entrar a cualquiera, y si se puede, hacer una limpieza de usuarios inactivos cuando se esté por llenar el cupo de 50."
   - The Access policy admits every authenticated identity. The app creates the user on their first request.
   - **The cleanup the owner asked for exists in Cloudflare.** It is seat expiration, under Zero Trust > Settings > Admin controls, "Remove inactive users from seats". It frees the seat of a user who has not signed in for a chosen period, and it is off by default. A removed user who signs in again takes a seat again. Source: https://developers.cloudflare.com/cloudflare-one/team-and-resources/users/seat-management/ (read 2026-10-21).
   - Freeing a seat does not delete the user's data in the app. Their keys, subscriptions and history stay.
   - Open sign-up meets R7: an unknown user may author a public strategy. What a new author may publish is part of Q9's area and is asked there.

3. **A subscription's size is a share of the subscriber's pool, chosen by the subscriber (Q3, 2026-10-21).** The owner chose "% del pool, lo elige el suscriptor".
   - It works as a strategy's share works today: a percentage of the subscriber's own pool on that exchange. It competes for the available capital with that user's other subscriptions.
   - The author decides nothing about a subscriber's money.
   - A new subscription joins at the strategy's next opening signal, never in the middle of an open position: entering at another price would make the subscriber's results differ from the strategy's. This is the default, stated here rather than asked.

4. **Leaving a strategy with a position open lets that position run until the strategy closes it (Q4, 2026-10-21).** The owner chose "Sigue hasta el cierre de la estrategia".
   - Leaving stops new openings at once.
   - The open position closes with the strategy's next closing signal, and only then does the subscription end. The subscriber's result matches the strategy's, and nothing is left without an owner.

5. **An author's disable and archive work as today, for every subscriber (Q5, 2026-10-21).** The owner chose "Como hoy, para todos".
   - Disabling stops the openings of every subscriber. Today the disabled check sits in capital allocation (`STRATEGY_DISABLED`, `allocate_capital.py:43`), so closing signals still close.
   - Archiving is allowed only when no subscriber holds an open position. Today archiving requires a disabled, flat strategy (`archive_strategy.py:2`).
   - An author who abandons a strategy leaves its subscribers with no closing signal. Each subscriber can close by hand on their exchange, and the reconciliation scan books that close. That booking path is not yet proven live (operator-panel cd.D.9). A close it cannot attribute lands in Discrepancies, which only the admin sees (R5).

6. **Going live needs a trade-capable key, and going back needs the user to be flat (Q6, 2026-10-21).** The owner chose "Live exige clave; volver exige estar plano".
   - A new user starts in simulation (rule 1, per user).
   - Moving to live takes a confirmation, and a trade-capable key stored on at least one exchange.
   - Moving back to simulation is refused while the user holds real open positions or reservations, with a message that lists them. So no real position is ever left without its real close.
   - The mode belongs to the user, not to each position.

7. **The server's `DRY_RUN` stays in `.env`, as an emergency brake for everyone (Q7, 2026-10-21).** The owner chose the first option, then asked: "yo como admin pasaría a usar el panel como usuario y podría usar DRY RUN true aunque en el .env estuviera en false?" Yes.
   - `DRY_RUN=true` keeps every user in simulation, whatever each one chose. The panel says so.
   - `DRY_RUN=false` lets each user's own mode decide, the admin's included. The admin is a user with their own mode: they may be in simulation while another user trades live.
   - A new deployment starts safe, because the setting defaults to true (rule 1).

8. **Besides Discrepancies, the admin sees a list of users with their state (Q8, 2026-10-21).** The owner chose "Una lista de usuarios con su estado".
   - Per user it shows:
     - the e-mail;
     - the mode (simulation or live);
     - the exchanges with a key, and whether any is degraded;
     - the number of subscriptions and of open positions;
     - the last sign-in.
   - It shows no amounts and no performance. The admin can support a user and understand a discrepancy without seeing anyone's portfolio.

9. **A new strategy is open to subscribers as soon as it is created (Q9, first part, 2026-10-21).** The owner chose "Al instante" over admin approval (the recommendation) and over publishing after a minimum history.
   - Nobody reviews a strategy before others can subscribe. The subscriber decides by looking at its history.
   - **Accepted risk:** with open sign-up (decision 2), a stranger can publish a strategy, and inexperienced users can trust it with money at once.
   - It follows that the public list must show each strategy's history clearly: its age, its closed trades and its return, and whether that return came from simulation or from live.

10. **An author sees how many subscribers they have and the total capital they assign (Q9, second part, 2026-10-21).** The owner chose "Cantidad y capital total".
    - The author sees the number of subscribers, and how many of them are live.
    - The author sees the sum of the capital the subscribers assign to the strategy, in the pool's settlement currency, never blended across currencies (rule 7).
    - No e-mail and no single subscriber's amount is shown.
    - Amended by decision 30: the sum is public and includes the author.

12. **Monetization is left out of this change (Q11, 2026-10-21).** The owner chose "Afuera por ahora".
    - This change builds the users, the subscriptions, the authors and the mode per user, all free of charge.
    - Charging, and the legal review it needs (operator-panel decision 4: possibly regulated, CNV), is a separate change, designed once there are real users.

13. **A user in simulation simulates against their real balance, read with their own key (design OQ1, 2026-10-21).** The owner chose "Su saldo real, con clave".
    - Simulation needs at least one stored key, and a read-only key is enough. A user with no key can browse, but cannot subscribe.
    - Results are measured against the real balance, so the public record is never inflated by invented money.

14. **The `DRY_RUN=true` brake stops real openings only; a real position closes for real (design OQ2, 2026-10-21).** The owner chose "Cierra en real".
    - This narrows decision 7. While the brake is on, nobody opens a real position. A real allocation that is already open closes for real when its signal arrives, in the mode recorded when it opened.
    - So the worker still loads the live keys of users who hold real open allocations, even while the brake is on.
    - The startup guard no longer refuses to start when `DRY_RUN=true` meets real open allocations. That combination is now a valid state.

15. **The public return of a strategy is measured from its signals (design OQ3, 2026-10-21).** The owner chose "El de las señales".
    - Each closed trade's return comes from the entry and exit prices of the alerts themselves, unleveraged and before fees. The list labels it that way.
    - Every strategy has a record from its first closed trade, whether or not anyone subscribes. No subscriber's share, leverage or fees can change it.
    - Beside it, the list shows the number of subscribers trading the strategy live. This replaces decision 9's "simulation vs live" label: a record taken from signals is neither.
    - Decision 9's other items stay: the strategy's age and its closed trades.

16. **PR B opens the owned endpoints that need no later PR to any signed-in user, scoped by `user_id`; the rest stay admin-only (PR B planning, 2026-10-21).** The owner chose "Si, vamos con esa división".
    - Open, scoped: keys (credentials), pools, performance and open positions. A resource of another user answers 404 (AD8), and each one has its cross-user test, which a 403 would make vacuous.
    - Admin-only: strategies and the pair catalogue (authoring is PR D, subscribing PR C), the webhook secret and origin, and discrepancies (R5).
    - Production does not change: Access still admits only the owner.

17. **The header keeps showing the signed-in user's e-mail until users choose a display name (owner question, 2026-10-26).** The owner chose "Esperamos" over masking the e-mail now.
    - The owner asked whether the header could show a masked e-mail, or a name each user chooses, instead of the full e-mail.
    - Masking in the panel hides only the user's own e-mail, which `/api/me` and the Access cookie carry to that same browser anyway. It guards against screenshots and screen sharing, not against the user.
    - Other users' e-mails are a different matter. A public strategy's author, for example, must never reach the client at all, so the backend sends a display name instead. That name arrives with the public strategies work (PR D). The header switches to it then.

18. **A new subscriber joins per symbol: at that symbol's next opening, never in the middle of that symbol's open position (PR C planning, 2026-10-27).** The owner chose "Si, por par" over waiting until the whole strategy is flat.
    - The question came from the code. The system keeps a strategy's position per (strategy, symbol) (`signals/infrastructure/repository.py:108`), but AD4 armed a subscription on "the last processed signal of the strategy", whatever its symbol. In a strategy that trades several pairs, the whole strategy may never be flat at once.
    - Example: a user subscribes while the strategy holds BTC and is flat on ETH. They enter at ETH's next opening, and at BTC's only after BTC closes.
    - This keeps decision 3's reason: every entry is at the strategy's own price.
    - It replaces AD4's `armed_at`, which is not built.

19. **Deleting a strategy takes its subscriptions with it (PR C, C.1, 2026-10-27).** The owner chose "Si" to the recommendation over letting subscriptions block the delete.
    - The delete still requires a strategy that never traded: no signals, reservations, ledger entries or booking proposals. The subscriptions are not part of that.
    - `fk_subscriptions_strategy` is `ON DELETE CASCADE`. The history check counts the subscriptions for the response body and the log line, and never blocks on them. Enablement events work the same way (decision 42).
    - Why not block: from 0031 on, every strategy carries its author's subscription, so a blocking count would make every delete impossible.
    - Once other users exist, their subscriptions to a strategy that never emitted a signal go with it too. They lose nothing, because nothing traded.
    - The question came from `test_strategy_references_guard`, which refuses any new reference into `strategies` that the delete check does not count. `PositionTransition` has no scale-in: every consuming effect is an entry at the signal's price, either an opening from flat or the opening half of a reverse. So every consuming effect goes to every ACTIVE subscription, and every releasing effect goes only to the subscriptions that hold that symbol's open allocation.

20. **Deleting a key is blocked by the user's ACTIVE subscriptions to ENABLED strategies on that market (PR C, C.10, 2026-10-28).** The owner chose "Solo las ACTIVE, como recomendas" over blocking on every subscription that is not ENDED.
    - Until now the delete was blocked by the enabled strategies the user authors. A subscriber authors nothing, so that read would let them delete the key a subscription still needs.
    - A disabled strategy fans out no signal, so its subscription needs no key. If the author enables it again, the subscriber's next opening is refused before any capital is reserved (`EXCHANGE_HAS_NO_KEY`), which is what happens to an author today.
    - A LEAVING subscription holds an open position, and that position already blocks the delete through the ledger holdings.

21. **An author may make a strategy private, chosen at creation and changeable afterwards; making it private keeps its current subscribers (2026-10-28, amends R7).** The owner asked for it ("Prefiero que se pueda cambiar luego de crearla") and chose "Los actuales siguen".
    - The owner's use case: run a strategy privately until it has a history, then publish it with data to analyse.
    - The public record is computed from the strategy's own signals (decision 15), never from a user's ledger, so the signals received while private are already the history when it turns public. That record always includes the private period, so going private never hides a bad run.
    - Going private blocks new subscriptions only: a subscription to another author's private strategy is refused as not found (AD8). Current subscribers keep receiving its signals, and the fan-out does not read the visibility. A subscriber who leaves cannot come back while it stays private.
    - A private strategy leaves the public list and its public page.
    - Accepted risk: an author may run several private strategies and publish only the lucky one. Nothing prevents that; the public history is the only mitigation, as in decision 9.
    - Deferred mitigation (owner, 2026-10-28): cap how many strategies a user may hold, by plan (for example free, pro, premium). It is decided later, once everything works, together with monetization (decision 12). For the cap to bite, it must also count archived and deleted strategies, or limit creations over time; otherwise an author retires the unlucky ones and creates new ones.
    - Scheduled for PR D (authoring): the column, the creation choice, the change, and the subscribe refusal. It must be in place before PR F opens the public list.

22. **An author cannot leave their own strategy (PR C, C.12, 2026-10-28).** The owner proposed it ("no me cierra que alguien cree una estrategia que no vaya a usar. Es un incentivo o ejemplo que da para otros usuarios") and confirmed "Dale, registrala y aplicala".
    - `Leave` refuses the author with 409 `AUTHOR_CANNOT_LEAVE`, before any lock or write. The author's way out is to disable the strategy (it stops for everyone) or to archive it (it ends every subscription, C.9).
    - The author's share may be small. The owner is fine with that, and described the practice it mirrors: a first bot runs with little real capital to confirm the backtest, and after one or two months it is published with that real history, as a percentage. Each copier then chooses their own capital, and leverage is each user's own (the system reads it from that user's account and never sets it).
    - So the author's subscription only gets a share editor. Subscribe and Leave appear in the panel with PR F, the first PR where a user sees a strategy they did not write. The owner's idea for that view: where the author has the enable toggle, another user has the Subscribe / Subscribed button.

23. **A strategy's name is unique per author, not across the system (PR D planning, 2026-10-29).** The owner chose "Si, me parece bien" to the recommendation.
    - Today `strategies.name` is unique across every user, and a taken name answers 409.
    - With many authors, that lets one user take a name from everyone else. With private strategies (decision 21) it also leaks: the 409 tells another user that a private strategy with that name exists.
    - So one author cannot repeat their own name, and two authors may share one. In the public list (PR F) the author's display name tells them apart.
    - Production holds one author, so the new unique is satisfied by today's rows.

24. **Copy stays enabled on a secret shown once, even with no webhook host configured (PR D, D.6, 2026-10-30).** The owner chose "Creo que convendría igualmente" to the recommendation to keep it.
    - Operator-panel decision 53 disables Copy on the webhook URL when no usable `webhook_public_origin` is configured, so an incomplete URL is never copied.
    - A secret is now shown once (AD6). Disabling Copy there would leave it to be transcribed by hand, or regenerated.
    - So the shown-once view copies the path with the secret and says to put the host in front. Decision 53 still holds everywhere else.

25. **The strategy page masks the webhook secret with its last four characters, as API keys are shown (after PR D's deploy, 2026-10-30).** The owner asked to replace the `<your secret>` placeholder with a mask "como las claves API", and chose "la 2 me parece bien" and then "Si, prefiero la 2" to storing a four-character hint over a fixed mask.
    - Only the secret's hash is stored (AD6), so no character of it can be shown unless it is kept apart. The owner asked why the secret cannot be shown again: keeping it readable means storing it, and a stored secret is what a database dump would leak; showing it from the vault would make the API decrypt, which rule 8 forbids.
    - The last four characters let the author tell which secret an alert carries, for instance after regenerating. They reveal 4 of 43 characters.
    - Existing strategies get the last four of today's `WEBHOOK_SECRET`, as 0033 gave them its hash.

26. **Moving to live is allowed with simulated positions open, and capital is counted per mode (PR E planning, 2026-10-30).** A position closes in the mode it opened in, so a user can go live while simulated positions wait days for their close signal, and the design said nothing about it. The owner chose "Dale, si. Lo que recomendas" to allowing the move and separating the capital, over refusing it until no simulated position is left.
    - The move takes effect at once. Simulated positions run until they close, in simulation.
    - `sum_active` counts only reservations of the mode being allocated: a simulated reservation never shrinks a real order, and a real one never shrinks a simulated order. Both read the same real balance (decision 13).
    - The user can hold real and simulated positions at the same time until the simulated ones close.
    - The reverse stays as decision 6 says: moving back to simulation is refused while the user holds anything real.

27. **An author appears under a display name they choose, and a strategy turns public only once its author has one (PR F planning, 2026-11-01).** Decisions 17 and 23 need that name and nothing had built it. The owner chose "Si, nombres" over a generated alias.
    - Each user chooses it in Settings. It is unique ignoring case, so nobody can pass as another author. The e-mail never reaches another user.
    - It is a nullable column on `users`, migration 0036, so PR F gains a rehearsal and an owner-run deploy.
    - The owner added that the active strategies are already `PUBLIC`, and none of them has a named author yet. So the rule acts on turning public, at creation or by a change, and a `PUBLIC` strategy with an unnamed author stays a valid state: its settings can still be edited, and the public list leaves it out until the author chooses a name. That follow-up was worked out from the owner's word, not asked.

28. **A strategy's public return is built as the panel builds its own (PR F planning, 2026-11-01).** Decision 15 defines a trade's return and left open how trades add up. The owner chose "Si, metodo del panel" over averaging each day's trades.
    - Trades closed on one UTC day are summed, and days are compounded, as in `performance/domain/curve.py`.
    - Each trade's return is taken as if the whole capital were on that trade. A strategy that gains 2 % on five pairs in one day shows +10 %. The list labels the figure as unleveraged and before fees.

29. **The public record is checked against the venue's price before sign-up opens (PR F planning, 2026-11-01).** The record comes from the `price` of the alerts (decision 15), and an alert's price is whatever its sender writes: nothing compares it with a venue. So an author with their own webhook secret can post prices that never existed and build any record, in simulation, at no cost. Decision 9's only mitigation is that history. The owner chose "Si, sumalo como requisito antes de abrir el registro" over accepting the risk.
    - When the worker processes a signal, it records the venue's public price. It happens in the worker, never at ingress, because of TradingView's 3-second limit (rule 3).
    - A price that cannot be read never stops a trade.
    - A trade whose alert price strays from the venue's by more than a margin does not count in the public record. The margin is set when the task is written.
    - It is readiness task D.5 of PR G, not part of PR F: only the owner can send signals until sign-up opens, so no stranger's signal goes unchecked.
    - It does not stop an author from trading by hand at real prices. That record is true.
    - **Superseded by decision 34:** the record no longer reads alert prices, so there is nothing left to check.

30. **A strategy's capital is one public figure, beside its number of subscribers (PR F planning, 2026-11-01; amends decision 10).** The owner proposed it so that anyone can see whether an author backs their own strategy, and chose one sum over separate figures for author and subscribers, and over any minimum number of subscribers: "Con una sola cifra y el numero de suscriptores considero que esta bien".
    - Every signed-in user sees it, not only the author, from the first subscriber on. The author counts as a subscriber.
    - It adds the author's capital and the subscribers' into one figure.
    - Accepted by the owner, in their words: "Solo un primer suscriptor podría ver cuanto capital puso el autor, y a partir del segundo apenas puede estimarlo. No me importa que sea asi." This gives up decision 10's "no single subscriber's amount" for strategies with one or two subscribers. No name or e-mail goes with it.
    - It is derived, not stored: each share times the latest balance of that pool. It is capital assigned, not capital in use, and the same money can stand behind several strategies, because strategies compete for one pool. A pool with no balance read adds nothing.
    - Stated to the owner, not asked: it counts only those trading live, like decision 15's count, because a simulation reads the real balance (decision 13) and would show money at no risk. The subscribe step says that the capital joins a public sum.
    - The author still sees their total of subscribers, simulated ones included (decision 10).

31. **A compounded return stops at -100% (PR F's verifier, 2026-11-01; amends decision 28).** A day's trades are summed, and each reads as if the whole capital were on it, so a day can pass -100%: twenty pairs at -7% sum to -140%. Compounded as it stood, two such days multiply into a gain, and thirty pairs at -7% on each of two days read +21%. The owner chose "Dale, piso de -100%": a day that loses everything leaves the index at zero, and it stays there, so a strategy's public record never comes back from it.
    - It lives in `compound`, which the pool and strategy curves also use, so they follow it. A day's own figure keeps its sum, -140% stays -140%.
    - A range is compounded on its own trades, so a 7D window that starts after a wipe-out still reads what those trades returned. A month or a chart window that starts from zero reads 0%.

32. **A display name cannot mix alphabets whose letters look alike (PR F's verifier, 2026-11-01; amends decision 27).** `Аna Lopez` with a Cyrillic `А` passed NFKC and the unique index beside `Ana Lopez` and read the same. The owner chose "Dale, rechazá los nombres que mezclen alfabetos".
    - The alphabets are Latin, Cyrillic, Greek, Armenian and Cherokee, the ones with letters that pass for Latin ones or for each other. Letters of two of them refuse a name. Other scripts may sit beside them, `Ana 李` is a name, and symbols and digits do not count.
    - It is not a whole defense: a name written wholly in Cyrillic can still imitate a Latin one, `Асе` reads as `Ace`. Refusing that would refuse every Cyrillic name that happens to use those letters.

33. **The price check's margin is 0.25 % (PR G planning, 2026-11-02; completes decision 29).** Set from production's own fills and stated to the owner, not asked. `measure_alert_gap.sh` read 20 live fills, all on Binance, none of them over 3 seconds after the alert: median gap 0.034 %, largest 0.145 %, none over 0.25 %.
    - The gap measured is alert price against fill price, so it holds the order's slippage, which a ticker read does not. It is 20 fills on one exchange: Bybit and Pionex are unmeasured, and a thin market will stray further.
    - It leans tight on purpose. An author who lies within the margin on both legs gains up to twice the margin on each trade, unseen: 0.5 % per trade here. A true trade that strays only leaves the public record.
    - It can be widened later. The verdict is derived when the record is built, so a new margin applies to the whole history with no data change.
    - **Superseded by decision 34:** no price check is built, so this margin is not used.

34. **A strategy's public record is its author's real trades, read from their fills (PR G, 2026-11-02; replaces decision 15's source, supersedes decisions 29 and 33).** The owner read SFP at -12.0 % over four trades, three of them simulated, and proposed it: "me parecería bien mostrar solo historial con trades reales. Para ver backtests de dinero simulado, ya tenemos tradingview". They refused a second figure beside it: "eso satura de informacion". On being told the fills make the price check unnecessary, they answered "Confirmo los tres".
    - A trade counts when the author held it live, closed. Its return comes from the fills of that allocation, as if the whole capital were on it, unleveraged and before fees. Decisions 28 and 31 still add the trades up. The list keeps showing the closed trades, now the real ones.
    - A strategy with no real closed trade is listed with no return, and says that it has none yet.
    - Only the author's trades count, in keeping with decision 22, so a subscriber's capital cannot give a strategy a record.
    - An alert's price no longer reaches the record, so a price nobody traded at cannot build one. The record stays a percentage, so it takes real money but very little of it, and an author can run several strategies small and leave public the one that went well.
    - Going back to simulation hides nothing already closed. As the owner put it, an author cannot predict the next trade, so skipping one gains nothing on average. What is left is stopping while ahead: the figure freezes at a good moment, and only the strategy's age against its closed trades shows it.

35. **A live opening is sized from the venue's price, never the alert's (PR G, 2026-11-02).** It was `granted * leverage / alert price`, so an author posting a tenth of the market price would have opened every live subscriber at ten times their granted margin, limited only by the venue. Found while checking decision 34. The owner confirmed it with "Confirmo los tres".
    **A simulated fill prints at the venue's mark price too (2026-11-04), superseding decision 45's alert price.** An author types the alert's price, and a Heikin Ashi chart computes one that never traded, so a simulated subscriber, who decides from those results whether to go live, read fills no venue would have given. The mark is read from each venue's public market data, so a user with no key simulates too; it sizes the simulated opening and prices both fills. The cost, accepted: an unreadable mark retries the simulated job, each simulated subscriber adds one weight-1 read on Binance per signal, and the author's simulation no longer matches TradingView's report to the cent. The owner chose it with "Dale, si".
    - The price is read when the order is built, as the leverage is. An opening whose price cannot be read is refused, also as the leverage is. This reverses decision 29's "a price that cannot be read never stops a trade" for openings only: a close does not depend on that price.

36. **A return curve starts at 0 on the day its first trade opened (2026-11-02; confirmed with "Confirmo el 0").** `E_0 = 1` existed in the arithmetic but was never drawn, so the line was born on the first close, with that trade already in it, reading +3 % where the owner expected 0.
    - The origin is the UTC day of the earliest `opened_at` among the trades the curve counts, because that is when capital went at risk. Not the strategy's activation: Overview mixes strategies with different dates, and a strategy enabled for a month with no signal would draw a flat line that reads as a record. Not the day before the first close: it would show a four-day trade as one day.
    - A window with earlier history starts at 0 on its left edge, which is the rebase's own base. Its first point inside was born above or below 0 in the same way.
    - A trade that opens and closes on one UTC day puts the origin the day before the close, so the two points do not fall on one x and draw a vertical line.
    - Not built. It goes with the panel requests in `tasks.md`, in its own delivery: sign-up does not depend on it.

37. **An exchange tab shows only where its user has something running (2026-11-02; proposed and confirmed with "Si, me parece bien").** The request: "Actualmente veo como pestañas Binance, Bybit y Pionex a pesar de solo tener la key configurada de Binance. Quisiera que solo se muestren las pestañas de exchanges configurados." The tabs came from the user's pools, not from their keys.
    - A tab shows when the user has a key on that exchange, a position open there, or an active strategy or subscription there. Closed history alone does not hold a tab: the data stays, and the tab returns with a key.
    - Not a key alone: a simulated opening needs no key, so a new user simulating with no key would have no tab and could not see their own positions.
    - Decision 80 settled the same thing for Settings' cards, which keep their own rule: an enabled pool with no key stays as an amber card.
    - Not built. It goes with the panel requests in `tasks.md`, in its own delivery.

11. **The existing data becomes the owner's (Q10, 2026-10-21; a default, stated rather than asked).** The owner becomes the first user and the admin, and owns today's strategies, keys, pools, ledger and signals. Nothing already recorded changes owner or meaning. The migration that adds the owner column fills it with the owner's user for every existing row. Like every migration, it is rehearsed on a throwaway copy first.
