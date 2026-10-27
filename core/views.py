"""Connect, Schema and Ask views. Owner: Maaz.

Each page's context has the shape documented in `core/sample_context.py`.
`?state=<name>` still renders the sample context, so templates can be built
and checked against every state without a database.
"""

from django.shortcuts import get_object_or_404, redirect, render

from agent.connection import mask_url
from core import sample_context, services
from core.forms import AskForm, ConnectForm
from core.models import DatabaseConnection


def _state(request) -> str | None:
    return request.GET.get("state")


def connection_dict(connection: DatabaseConnection) -> dict:
    """The `connection` shape of sample_context.CHINOOK."""
    snapshot = connection.snapshots.order_by("-captured_at").first()
    return {
        "id": connection.id,
        "name": connection.name,
        "dialect": connection.dialect,
        "readonly_verified": connection.readonly_verified,
        "table_count": snapshot.table_count if snapshot else 0,
        "created_at": connection.created_at,
    }


def connect(request):
    if _state(request):
        return render(request, "connect.html", sample_context.connect(_state(request)))
    form, check = ConnectForm(), None
    if request.method == "POST":
        form = ConnectForm(request.POST)
        if form.is_valid():
            name, url = form.cleaned_data["name"], form.cleaned_data["url"]
            check, connection = services.connect_database(name, url)
            # Never send the password back to the browser (FR-C3).
            form = ConnectForm() if connection else ConnectForm(data={"name": name, "url": mask_url(url)})
    connections = [connection_dict(c) for c in DatabaseConnection.objects.all()]
    return render(request, "connect.html", {"form": form, "connections": connections, "check": check})


def schema(request, connection_id: int):
    """POST fields: `action` = "save" or "refresh"; with "save", the ticked boxes
    `restricted_tables` (table names) and `restricted_columns` ("table.column")."""
    if _state(request):
        return render(request, "schema.html", sample_context.schema(_state(request)))
    connection = get_object_or_404(DatabaseConnection, pk=connection_id)
    error = None
    if request.method == "POST":
        if request.POST.get("action") == "refresh":
            error = services.refresh_schema(connection)
        else:
            services.save_restricted(connection, request.POST.getlist("restricted_tables"),
                                     request.POST.getlist("restricted_columns"))
        if not error:
            return redirect("schema", connection_id=connection.id)

    snapshot, schema_ = services.latest_schema(connection)
    tables = []
    for t in schema_.tables.values():
        fk_of = {col: f"{fk.ref_table}.{ref}" for fk in t.foreign_keys for col, ref in zip(fk.columns, fk.ref_columns)}
        hidden = schema_.restricted_columns_of(t.name)
        tables.append({
            "name": t.name,
            "restricted": t.name in schema_.restricted_tables,
            "columns": [
                {"name": c.name, "type": c.type, "nullable": c.nullable, "primary_key": c.primary_key,
                 "foreign_key": fk_of.get(c.name, ""), "restricted": c.name in hidden,
                 "sample_values": list(c.sample_values)}
                for c in t.columns
            ],
        })
    return render(request, "schema.html", {
        "connection": connection_dict(connection),
        "captured_at": snapshot.captured_at,
        "tables": tables,
        "error": error,
    })


def ask(request, connection_id: int):
    # TODO(Maaz, Phase 6): on POST call core.services.answer_question.
    ctx = sample_context.ask(_state(request) or "default")
    ctx["form"] = AskForm(initial={"question": ctx["question"]})
    return render(request, "ask.html", ctx)
