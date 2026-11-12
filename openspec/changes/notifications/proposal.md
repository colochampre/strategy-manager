# Notifications

Not planned yet: a placeholder so the requirement is not lost.

Owner, 2026-11-12, announced as a request coming soon: "un sistema de
notificaciones, con las aperturas y cierres de las estrategias suscritas, con
opción de recibirlas por Telegram, WhatsApp, email o solo la app. El usuario
elije donde recibirlas".

It must also deliver the safety events of `subscriber-safety` (stop fired,
position closed because its strategy was disabled, archived or lost its
author).

Each channel is a processor of personal data (a chat id, a phone number, an
address), so it updates the privacy policy and bumps `PRIVACY_VERSION`.
