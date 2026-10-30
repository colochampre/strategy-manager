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

11. **The existing data becomes the owner's (Q10, 2026-10-21; a default, stated rather than asked).** The owner becomes the first user and the admin, and owns today's strategies, keys, pools, ledger and signals. Nothing already recorded changes owner or meaning. The migration that adds the owner column fills it with the owner's user for every existing row. Like every migration, it is rehearsed on a throwaway copy first.
