"""Template context shared by every page."""

from core.models import DatabaseConnection

SESSION_KEY = "connection_id"   # the database last opened on Connect, Schema or Ask


def current_connection(request) -> dict:
    """`nav_connection`: the last-used connection, so the nav keeps its Schema and Ask
    links on pages that are not about one connection (Connect, Log)."""
    connection_id = request.session.get(SESSION_KEY) if hasattr(request, "session") else None
    connection = DatabaseConnection.objects.filter(pk=connection_id).first() if connection_id else None
    if connection is None:
        return {"nav_connection": None}
    return {"nav_connection": {"id": connection.id, "name": connection.name,
                               "readonly_verified": connection.readonly_verified}}
