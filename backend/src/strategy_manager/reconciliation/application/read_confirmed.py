"""``ReadConfirmed``: the read behind the confirmed-discrepancies view
(design.md PR 15 addendum § G; owner decision 66 Q5 and Q6, 2026-10-16).
"""


class ReadConfirmed:
    async def read(self) -> tuple[()]:
        return ()
