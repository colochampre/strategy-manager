# Notifications

Not planned yet: a placeholder so the requirement is not lost.

Owner, 2026-11-12, announced as a request coming soon: "un sistema de
notificaciones, con las aperturas y cierres de las estrategias suscritas, con
opción de recibirlas por Telegram, WhatsApp, email o solo la app. El usuario
elije donde recibirlas".

It must also deliver the safety events of `subscriber-safety` (stop fired,
position closed because its strategy was disabled, archived or lost its
author).

It must also deliver an opening that was refused for something the user has
to fix at the exchange, because a user who never opens the panel would not
learn of it: `LEVERAGE_CONFLICT`, `LEVERAGE_NOT_APPLIED`,
`MARGIN_NOT_ISOLATED`, a Bybit account not on isolated margin, a hedged
account, a read-only key.

And the quiet notice of `manual-trading`: a position on a symbol the system
never traded for that user, delivered to that user without a push.

Each channel is a processor of personal data (a chat id, a phone number, an
address), so it updates the privacy policy and bumps `PRIVACY_VERSION`.
