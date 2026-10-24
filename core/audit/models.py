"""QueryLog and QueryCache. Owner: Sunil (Phase 3).

Fields are specified in the "Data Model" note. Models defined here are
registered through the import at the top of `core/models.py`, so migrations
go in `core/migrations/` (`python manage.py makemigrations core`).

Reference the connection as "core.DatabaseConnection" (a string) to avoid a
circular import.
"""

# TODO(Sunil): QueryLog, QueryCache
"""QueryLog and QueryCache. Owner: Sunil (Phase 3).

Fields are specified in the "Data Model" note. Models defined here are
registered through the import at the top of `core/models.py`, so migrations
go in `core/migrations/` (`python manage.py makemigrations core`).

Reference the connection as "core.DatabaseConnection" (a string) to avoid a
circular import.
"""

from django.db import models


class QueryLog(models.Model):
    VERDICTS = [
        ("answered", "answered"),
        ("blocked", "blocked"),
        ("failed", "failed"),
    ]

    connection = models.ForeignKey(
        "core.DatabaseConnection", on_delete=models.CASCADE, related_name="query_logs"
    )
    question = models.TextField()
    plan_json = models.JSONField(null=True, blank=True)
    final_sql = models.TextField(blank=True, default="")
    attempts_json = models.JSONField(default=list)
    verdict = models.CharField(max_length=10, choices=VERDICTS)
    rules_fired = models.JSONField(default=list)
    attempt_count = models.IntegerField(default=1)
    rows_returned = models.IntegerField(null=True, blank=True)
    exec_ms = models.IntegerField(null=True, blank=True)
    anomaly_flags = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.verdict}] {self.question[:50]}"


class QueryCache(models.Model):
    connection = models.ForeignKey(
        "core.DatabaseConnection", on_delete=models.CASCADE, related_name="query_cache"
    )
    question_normalised = models.TextField()
    schema_hash = models.CharField(max_length=64)
    sql = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("connection", "question_normalised", "schema_hash")

    def __str__(self):
        return self.question_normalised[:50]