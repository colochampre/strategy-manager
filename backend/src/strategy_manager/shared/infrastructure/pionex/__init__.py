"""Pionex REST adapters.

Lives under ``shared/infrastructure`` because the signed transport is needed
by more than one module — ``accounts`` reads balances today, ``execution``
will submit orders later — and duplicating it, or importing across two
sibling modules' infrastructure, is worse than sharing it here.

Nothing in ``domain`` or ``application`` may import this package. Pionex is
an adapter, never the centre (CLAUDE.md § Architecture).
"""
