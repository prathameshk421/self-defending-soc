"""Typed errors for the ingest layer."""


class IngestError(Exception):
    """Base for ingest errors."""


class ConfigInvalid(IngestError):
    """Ingest configuration failed validation (fail closed)."""


class SchemaRegistryError(IngestError):
    """Schema registry unreachable or returned an unexpected response."""


class SchemaIncompatible(IngestError):
    """Local schema conflicts with the registered schema (fail closed)."""
