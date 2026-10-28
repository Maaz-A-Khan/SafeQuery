"""Connect, Schema and Ask views. Owner: Maaz.

Each page's context has the shape documented in `core/sample_context.py`.
`?state=<name>` still renders the sample context, so templates can be built
and checked against every state without a database.
"""

import csv

from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET

from agent.connection import mask_url
from core import sample_context, services
from core.audit.models import QueryLog
from core.forms import AskForm, ConnectForm
from core.models import DatabaseConnection

DISPLAY_ROW_LIMIT = 100   # rows shown on the Ask page; the CSV has all of them (FR-U5)


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
    """POST field: `question`. The answer is rendered straight away; rows are never stored."""
    if _state(request):
        ctx = sample_context.ask(_state(request))
        ctx["form"] = AskForm(initial={"question": ctx["question"]})
        return render(request, "ask.html", ctx)
    connection = get_object_or_404(DatabaseConnection, pk=connection_id)
    form, result, csv_url = AskForm(), None, None
    if request.method == "POST":
        form = AskForm(request.POST)
        if form.is_valid():
            result, log_id = services.answer_question(connection.id, form.cleaned_data["question"])
            if result.outcome == "answered" and log_id is not None:
                csv_url = reverse("ask_csv", args=[connection.id, log_id])
    return render(request, "ask.html", {
        "connection": connection_dict(connection),
        "question": result.question if result else "",
        "result": result,
        "form": form,
        "display_row_limit": DISPLAY_ROW_LIMIT,
        "csv_url": csv_url,
    })


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _csv_cell(value) -> str:
    """A cell as text, defused against spreadsheet formula injection."""
    if value is None:
        return ""
    text_value = str(value)
    return "'" + text_value if text_value.startswith(_FORMULA_START) else text_value


@require_GET
def ask_csv(request, connection_id: int, log_id: int):
    """Download an answered question's rows as CSV (FR-U5): the logged final SQL is
    validated and run again on the read-only connection; nothing is stored."""
    get_object_or_404(DatabaseConnection, pk=connection_id)
    try:
        outcome = services.csv_rows(connection_id, log_id)
    except QueryLog.DoesNotExist:
        raise Http404("No answered question with that id.")
    if isinstance(outcome, str):
        return HttpResponse(outcome, status=409, content_type="text/plain; charset=utf-8")
    columns, rows = outcome
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="safequery-{log_id}.csv"'
    response.write("\ufeff")   # BOM so Excel reads UTF-8
    writer = csv.writer(response)
    writer.writerow(columns)
    writer.writerows([_csv_cell(v) for v in row] for row in rows)
    return response
