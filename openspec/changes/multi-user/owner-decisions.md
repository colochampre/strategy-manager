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

## Open questions (asked one at a time, in this order)

- Q1. How a user is identified: the e-mail Cloudflare Access already verifies, or a login of the app's own.
- Q2. Who may become a user: invited by the admin only, or anyone who signs up.
- Q3. A subscription's size: a share of the subscriber's pool set by the subscriber, as a strategy's share is today, or something else.
- Q4. Joining and leaving a strategy with a position open: whether a new subscriber waits for the next opening signal, and what happens to an open position when a subscriber leaves.
- Q5. An author who disables or archives a strategy that has subscribers with open positions.
- Q6. Moving to live: what the confirmation requires (for example a trade-capable key stored first), and whether going back to simulation is refused while live positions are open.
- Q7. Whether the server's `DRY_RUN` stays as a global override that keeps everyone in simulation regardless of each user's choice.
- Q8. What the admin sees of other users (their positions, their keys' state, their performance) besides Discrepancies.
- Q9. What an author sees of their subscribers.
- Q10. The existing data: the owner becomes the first user and admin, and today's three strategies and their history become theirs.
- Q11. Monetization: designed now, or left out of this change.

## Decisions

None taken yet.
