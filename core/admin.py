from django.contrib import admin

from core.audit.models import QueryCache, QueryLog
from core.models import DatabaseConnection, SchemaSnapshot


@admin.register(DatabaseConnection)
class DatabaseConnectionAdmin(admin.ModelAdmin):
    list_display = ["name", "dialect", "readonly_verified", "created_at"]
    exclude = ["url_encrypted"]   # never shown (FR-C12)


@admin.register(SchemaSnapshot)
class SchemaSnapshotAdmin(admin.ModelAdmin):
    list_display = ["connection", "table_count", "captured_at"]


class RuleFiredFilter(admin.SimpleListFilter):
    title = "rule fired"
    parameter_name = "rule"

    def lookups(self, request, model_admin):
        return [(f"R{i}", f"R{i}") for i in range(1, 12)]

    def queryset(self, request, queryset):
        return queryset.filter(rules_fired__contains=[self.value()]) if self.value() else queryset


@admin.register(QueryLog)
class QueryLogAdmin(admin.ModelAdmin):
    """Read-only: an audit log that can be edited is not an audit log."""

    list_display = ["created_at", "connection", "question", "verdict", "stopped_by", "rules_fired",
                    "attempt_count", "rows_returned", "anomaly_flags"]
    list_filter = ["verdict", "stopped_by", RuleFiredFilter, "connection", "from_cache"]
    search_fields = ["question", "final_sql"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(QueryCache)
class QueryCacheAdmin(admin.ModelAdmin):
    list_display = ["question_normalised", "connection", "created_at"]
    list_filter = ["connection"]
