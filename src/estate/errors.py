"""Typed errors for Estate inventory load and query."""


class EstateError(Exception):
    """Base for estate errors."""


class InventoryInvalid(EstateError):
    """Inventory failed validation or policy checks (fail closed)."""


class NotFound(EstateError):
    """Asset or alias not found."""


class AmbiguousAlias(EstateError):
    """Alias matched more than one asset (should be prevented at load)."""


class RespondForbidden(EstateError):
    """Asset must not be a respond/isolate target."""
