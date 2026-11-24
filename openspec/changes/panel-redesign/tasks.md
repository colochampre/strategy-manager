# Tasks: Panel redesign

Redesign of the whole panel, keeping the palette (`frontend/src/index.css`, `@theme`). Inspired by oficinavirtual.edelap.com.ar and binance.com. Branch `design/panel-redesign` for the prototype, then one branch per PR, sequential. Test runner for the panel: `npm test` and `npm run lint` in `frontend/`.

## Specs

The owner's words (2026-11-24) are quoted as written.

- **S1 Hide balances.** "Modo ocultar saldos". Agreed with the owner:
  - The amounts, the absolute PnL, and the charts' axes and tooltips are hidden. The percentages stay visible: the owner decided "Los porcentajes visibles me parecen bien" (2026-11-24).
  - The choice is stored in the browser, not on the server.
  - The toggle is an eye beside the balance, as on Binance.
- **S2 Layout.** "Rediseño de la página, manteniendo la paleta de colores - inspirado en oficinavirtual.edelap.com.ar y binance.com". "Me gusta el espaciado de main de oficinavirtual, centrado y con buen margen, sin alargarse para ocupar todo el ancho. Lo mismo pasa en Binance."
  - Agreed: every page gets a breadcrumb, a title and a subtitle, as in Edelap's "Mis facturas".
- **S3 Mobile.** "En mobile, el sidebar puede ser desplegable lateral para poder seguir leyendo las opciones, con su botón hamburguesa."
  - Agreed: the drawer replaces today's `BottomNav`.
  - Agreed: the exchange buttons scroll sideways when they do not fit.
- **S4 Sidebar.**
  - "Parte superior con brand-logo, Panel de control (overview), Notificaciones, Mis operaciones y Estrategias."
  - "Estrategias desplegable con Mis estrategias, Mis suscripciones y Explorar, como en el sidebar de Binance."
  - "Nueva opción Vincular Exchange donde se gestionan las API keys con su respectiva vista. Se separa de la configuración de nombre del usuario y sus datos."
  - "En la parte inferior del sidebar: Mi cuenta y Cerrar sesión, como en oficinavirtual."
  - "Para admin, mover a una opción desplegable las opciones que solo sean visibles para admin en la parte inferior del sidebar, como /users."
  - Agreed with the owner:
    - Discrepancies go into that admin group.
    - The foot of the sidebar names the commit of the bundle being served (`build.txt`).
    - On desktop the sidebar can be collapsed.
- **S5 My trades.** "Mis operaciones: ejemplo visual oficinavirtual.edelap.com.ar/mis-facturas". "Lista de operaciones unificadas, para no tener que acceder a cada estrategia para ver todas las operaciones. Las operaciones de cada estrategia queda en su vista."
  - Agreed: filters by period, strategy and exchange.
  - Agreed: a state on each row (open, closed, closed by the stop, closed from the panel).
  - It needs a new paginated API endpoint.
- **S6 Notifications.** "Los Eventos de seguridad pasan a mostrarse junto con notificaciones, para resumir las opciones." "Las notificaciones pasan a tener color para diferenciarlas entre operaciones normales, eventos de seguridad, discrepancias, etc."
  - Agreed: the first version is a feed with colours and no read state.
  - Agreed: a bell sits in the icons at the top right.
  - Agreed: discrepancies appear to the admin only.
  - The colours are new semantic tokens in `@theme`.
  - The delivery channels belong to `openspec/changes/notifications/`.
- **S7 No top bar.** "Ya no hace falta el navbar superior":
  - "Las pestañas de exchanges pasan a verse encima de la primer tarjeta del panel del lado izquierdo como botones."
  - "El nombre de usuario pasa a ser un icono de persona y se muestra junto al lenguaje y modo en vivo/simulación a la misma altura que los botones de Exchange del lado derecho. El botón lleva a Mi cuenta"
  - "El estado En Vivo/Simulación queda a la izquierda de los iconos de usuario y lenguaje."
  - "Que los iconos queden del mismo tamaño."
- **S8 Dashboard.** "La primer tarjeta muestra la fila de datos de la cuenta, como saldo, PnL y return, drawdown, etc." "Tarjeta header con el saldo del Exchange seleccionado activo, valores de rendimiento y drawdown".
  - Rule 7 applies: there is no total blended across currencies. An exchange with several pools shows one figure per currency.
- **S9 Link an exchange.** The owner sent Edelap's "Mis suministros" as the example for managing API keys, "una mejora con respecto al nuestro". It shows:
  - a "Vincular" button across the top;
  - a "Vinculados" card with a filter, the total, and a table with actions on each row.

## Tasks

- [ ] RD.0 Static prototype in `visual/project/Redesign.html`, covering S1 to S9 with fictitious data. Route: delegated, as a Sonnet writer, for the parent's context backstop. Rendered with headless Edge before the owner sees it.
  - *Drawn 2026-11-24.* Seven screens, `ex1` to `ex7`, in 785 lines. The parent looked at `ex1` and `ex3` rendered. Waiting on the owner's review.
  - The notification tokens are `notif-operation` (gain), `notif-safety` (loss), `notif-discrepancy` (decision) and `notif-notice` (ink-2). Each has an edge colour, a soft fill made with `color-mix` over the panel, and an ink colour.
  - The writer assumed these, for the owner to correct:
    - In `ex2` the percentages stay visible.
    - The exchange buttons show the exchange's name in its brand colour, standing in for the logotype.
    - Some copy is invented: "Visible solo para administradores", the note on Mi cuenta and the description of the mode.
  - *Extended 2026-11-24 (L3).* Three more screens bring the file to 1192 lines; the parent looked at `ex8` rendered.
    - `ex8` My subscriptions and `ex9` Explore list every exchange, so they have no exchange buttons. `ex10` My strategies filters by the selected exchange, as `StrategiesPage` does today, so it keeps them.
    - The sidebar's sub-items replace today's three tabs.
    - The line "Hay 1 estrategia archivada oculta" in `ex10` is new; the app does not show it today.
    - In `ex3`, the build tag sits higher in the drawer.
- [ ] RD.1 PR 1, the shell: sidebar, drawer, top-right icons, centred main (S2, S3, S4, S7).
- [ ] RD.2 PR 2: Mi cuenta and Vincular exchange separated (S4, S9).
- [ ] RD.3 PR 3: the dashboard's header card, and hide balances (S1, S8).
- [ ] RD.4 PR 4: My trades (S5).
- [ ] RD.5 PR 5: Notifications (S6).

## Log

- L1 (2026-11-24, owner): "Quiero hacer un rediseño general de la app. Comentame si te parece bien, qué cambiarías o si falta algo:" followed by S1 to S8 as quoted, with screenshots of Edelap's home, Binance's assets overview and Edelap's "Mis facturas".
- L2 (2026-11-24, owner): the assistant proposed the additions marked "Agreed" above, and the five sequential PRs. The owner answered: "Me parece bien todo. Agrego un ejemplo más para vincular las api key que me pareció una mejora con respecto al nuestro: [Edelap, Mis suministros]. Dale, vamos con un prototipo".
- L3 (2026-11-24, owner, after reading the prototype): "Esta muy bien todo. Los porcentajes visibles me parecen bien. Lo único que faltaría en el prototipo son las vistas de estrategias, las suscritas, explore y propias. Si podemos agregarlas al prototipo, mejor". RD.0 reopened for three more screens: My subscriptions, Explore, and My strategies.
