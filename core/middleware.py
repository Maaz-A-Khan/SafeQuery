"""Refuse every request that does not come from this machine (NFR-S7)."""

from django.http import HttpResponseForbidden

LOOPBACK = {"127.0.0.1", "::1"}


class LocalOnlyMiddleware:
    """Connect and Ask need no login, so the app must be unreachable from other
    machines, even if someone runs `runserver 0.0.0.0:8000`."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.META.get("REMOTE_ADDR") not in LOOPBACK:
            return HttpResponseForbidden("SafeQuery only accepts requests from this computer.")
        return self.get_response(request)
