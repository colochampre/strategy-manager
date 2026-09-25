"""PR 3 (1b.5): decision 18 (ONE key per exchange) retires the `.env`
Bybit/Binance key pair entirely -- the single envelope-encrypted vault
credential signs every read AND every order, on both venues.

Two tests pin that from opposite directions:

  - the ``Settings`` model itself carries no field a `.env` key could still
    land in (``extra="ignore"`` already makes a leftover `.env` line
    harmless, per the deploy runbook -- this is the OTHER half: nothing in
    ``Settings`` reads it back even if it were there);
  - a repo-wide scan of every PRODUCTION module (``src/`` and ``scripts/``)
    for a reference to one of the retired field names, or an import of
    either venue factory's retired ``credentials_from_settings``.

Pionex is explicitly OUT of scope: its `.env` read-only key and
``credentials_from_settings`` predate this decision and this decision does
not touch them (design.md's technical approach names Bybit and Binance only).
"""

from pathlib import Path

from strategy_manager.shared.config import Settings

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_SCAN_ROOTS = (_BACKEND_DIR / "src", _BACKEND_DIR / "scripts")

_FORBIDDEN_FIELD_NAMES = (
    "bybit_api_key",
    "bybit_api_secret",
    "binance_api_key",
    "binance_api_secret",
)


def test_settings_carries_no_bybit_or_binance_key_field() -> None:
    fields = Settings.model_fields
    for name in _FORBIDDEN_FIELD_NAMES:
        assert name not in fields, (
            f"Settings.{name} must not exist -- decision 18's one vault "
            "credential per exchange leaves no `.env` field for it to fill"
        )


def test_grep_finds_no_production_reader_of_env_bybit_or_binance_key() -> None:
    """A text scan, not an import check: a reader that survives as a
    string-typo (``getattr(settings, "binance_api_key", "")``, a stale
    f-string) would pass every other test in this suite and still be a live
    landmine the moment somebody re-adds the field to ``Settings``."""
    offenders: list[str] = []
    for root in _SCAN_ROOTS:
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            relative = path.relative_to(_BACKEND_DIR)
            # Case-insensitive: ``os.environ["BINANCE_API_KEY"]`` reads the
            # same `.env` line as the retired field, just without Settings.
            lowered = text.lower()
            for name in _FORBIDDEN_FIELD_NAMES:
                if name in lowered:
                    offenders.append(f"{relative}: references '{name}'")
            if "bybit.factory import" in text and "credentials_from_settings" in text:
                offenders.append(
                    f"{relative}: still imports Bybit's credentials_from_settings"
                )
            if "binance.factory import" in text and "credentials_from_settings" in text:
                offenders.append(
                    f"{relative}: still imports Binance's credentials_from_settings"
                )

    assert not offenders, "\n" + "\n".join(offenders)
