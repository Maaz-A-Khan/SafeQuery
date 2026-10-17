"""Connect, Schema and Ask views. Owner: Maaz.

Phase 1: every view renders its sample context (see `core/sample_context.py`).
Phases 5 and 6 replace each body with real data of the same shape.
"""

from django.shortcuts import render

from core import sample_context
from core.forms import AskForm


def _state(request) -> str:
    return request.GET.get("state", "default")


def connect(request):
    # TODO(Maaz, Phase 5): handle POST, run the checks, list saved connections.
    return render(request, "connect.html", sample_context.connect(_state(request)))


def schema(request, connection_id: int):
    # TODO(Maaz, Phase 5): load SchemaSnapshot; POST saves restricted tables or refreshes.
    return render(request, "schema.html", sample_context.schema(_state(request)))


def ask(request, connection_id: int):
    # TODO(Maaz, Phase 6): on POST call core.services.answer_question.
    ctx = sample_context.ask(_state(request))
    ctx["form"] = AskForm(initial={"question": ctx["question"]})
    return render(request, "ask.html", ctx)
