"""Connections and cached schemas. Owner: Maaz. Audit models live in `core/audit/models.py`."""

from django.db import models

from agent.types import Dialect
from core.audit.models import *  # noqa: F401,F403  (registers Sunil's QueryLog and QueryCache)


class DatabaseConnection(models.Model):
    name = models.CharField(max_length=100)        # e.g. "Chinook (Postgres)"
    url_encrypted = models.BinaryField()           # Fernet; never logged or shown (FR-C12)
    dialect = models.CharField(max_length=20, choices=[(d.value, d.value) for d in Dialect])
    readonly_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class SchemaSnapshot(models.Model):
    connection = models.ForeignKey(DatabaseConnection, on_delete=models.CASCADE, related_name="snapshots")
    schema_json = models.JSONField()               # agent.types.Schema.to_json()
    restricted_tables = models.JSONField(default=list)
    table_count = models.IntegerField()
    captured_at = models.DateTimeField(auto_now=True)

    class Meta:
        get_latest_by = "captured_at"

    def __str__(self):
        return f"{self.connection} @ {self.captured_at:%Y-%m-%d %H:%M}"
