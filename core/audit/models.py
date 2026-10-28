"""QueryLog and QueryCache. Owner: Sunil (Phase 3).

Fields are specified in the "Data Model" note. Models defined here are
registered through the import at the top of `core/models.py`, so migrations
go in `core/migrations/` (`python manage.py makemigrations core`).

Reference the connection as "core.DatabaseConnection" (a string) to avoid a
circular import.
"""

from django.db import models

from agent.types import Outcome, StoppedBy


class QueryLog(models.Model):
    """The audit log: one row per question (FR-L1). Never holds result rows or
    connection strings (FR-L2)."""

    connection = models.ForeignKey(
        "core.DatabaseConnection", on_delete=models.CASCADE, related_name="query_logs"
    )
    question = models.TextField()
    plan_json = models.JSONField(null=True, blank=True)       # sub-questions, if multi-step
    final_sql = models.TextField(blank=True, default="")      # SQL that ran, else the last generated
    attempts_json = models.JSONField(default=list)
    verdict = models.CharField(max_length=10, choices=[(o.value, o.value) for o in Outcome])
    stopped_by = models.CharField(
        max_length=10, choices=[(s.value, s.value) for s in StoppedBy], default=StoppedBy.NONE.value
    )                                                         # D-007
    from_cache = models.BooleanField(default=False)
    rules_fired = models.JSONField(default=list)
    attempt_count = models.IntegerField(default=0)
    rows_returned = models.IntegerField(null=True, blank=True)  # null if not executed
    exec_ms = models.IntegerField(null=True, blank=True)
    anomaly_flags = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["connection", "-created_at"])]   # anomaly flag lookups

    def __str__(self):
        return f"[{self.verdict}] {self.question[:50]}"


class QueryCache(models.Model):
    """SQL of answered questions, keyed by normalised question and schema hash (FR-L4)."""

    connection = models.ForeignKey(
        "core.DatabaseConnection", on_delete=models.CASCADE, related_name="query_cache"
    )
    question_normalised = models.TextField()
    schema_hash = models.CharField(max_length=64)
    sql = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["connection", "question_normalised", "schema_hash"], name="unique_cache_entry"
            )
        ]

    def __str__(self):
        return self.question_normalised[:50]
