from django.contrib import admin

from core.models import DatabaseConnection, SchemaSnapshot


@admin.register(DatabaseConnection)
class DatabaseConnectionAdmin(admin.ModelAdmin):
    list_display = ["name", "dialect", "readonly_verified", "created_at"]
    exclude = ["url_encrypted"]   # never shown (FR-C12)


@admin.register(SchemaSnapshot)
class SchemaSnapshotAdmin(admin.ModelAdmin):
    list_display = ["connection", "table_count", "captured_at"]

# TODO(Sunil): register QueryLog with filters on verdict, rule and connection.
