"""The one exception that means "this process refused its own start".

Standard library only. It is deliberately NOT an ``InvariantViolation``: that
class is raised by runtime code too (a fill with a negative quantity, a signer
handed an empty key), and a runtime failure must keep ending in an ordinary
non-zero exit so systemd restarts the worker. Only the worker's startup phase
raises this one, and ``worker.main`` is the only place that maps it to an exit
code (owner decision 29).
"""


class StartupRefused(Exception):
    """A startup check refused to let the process begin claiming work.

    ``logged`` records whether the refusal already wrote its own ERROR. The
    alert bridge forwards log records and never exceptions, so every refusal
    needs exactly one ERROR before the process exits; a check that has written
    a richer one than its exception message says so here, and the worker does
    not write a second.
    """

    def __init__(self, message: str, *, logged: bool = False) -> None:
        super().__init__(message)
        self.logged = logged
