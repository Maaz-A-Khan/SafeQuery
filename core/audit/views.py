"""Log page views, superuser only (FR-L5). Owner: Sunil (Phase 3).

Phase 1: renders the sample context. Replace with QueryLog queries that
produce the same keys (see `core/sample_context.py`, "Log").
"""

from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import render

from core import sample_context

superuser_required = user_passes_test(lambda u: u.is_superuser)


@superuser_required
def log(request):
    # TODO(Sunil): QueryLog rows, filtered by ?verdict= and ?rule=
    return render(request, "log.html", sample_context.log(request.GET.get("state", "default")))


@superuser_required
def log_detail(request, entry_id: int):
    # TODO(Sunil): one QueryLog row with every attempt
    return render(request, "log_detail.html", sample_context.log_detail())
