"""Test-only reading of Accounting (2026-11-17 owner decision: the API keeps only the reads the screen uses).

GET /api/accounting answers only ?view=list&legacy=open, ?view=page and ?view=options; the parameterless,
?view=list and ?view=list&legacy=history reads were retired. Suites that verify payment schedules and
transactions still need the complete computation, so they read it here: the same view, the same permission
check (login, accounting.read, password change) and the same JSON as the retired reads returned.
Queries that the API still serves go through the real HTTP endpoint.
"""
import json
from urllib.parse import parse_qs

from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.signed_cookies import SessionStore
from django.test import RequestFactory
from rest_framework.renderers import JSONRenderer

SERVED = ({"view": ["list"], "legacy": ["open"]},)


class Result:
    """The parts of a test-client response the suites use."""

    def __init__(self, status_code, content):
        self.status_code, self.content = status_code, content

    def json(self):
        return json.loads(self.content)


def _served(query):
    params = parse_qs(query.lstrip("?"))
    return params.get("view") in (["page"], ["options"]) or any(all(params.get(k) == v for k, v in rule.items()) for rule in SERVED)


def accounting_get(client, query=""):
    """client.get('/api/accounting' + query) for every read the API ever had."""
    query = query if not query or query.startswith("?") else "?" + query
    if _served(query):
        return client.get("/api/accounting" + query)
    from cases.accounting_views import AccountingView
    from cases.calc.jsnum import json_roundtrip
    from rest_framework.response import Response
    request = RequestFactory(HTTP_HOST="localhost").get("/api/accounting" + query)
    user_id = client.session.get("_auth_user_id") if hasattr(client, "session") else None
    if user_id:
        request.user = get_user_model().objects.get(pk=user_id)
    else:
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()
    request.session = SessionStore()
    view = AccountingView()
    view.setup(request)
    drf = view.initialize_request(request)
    view.request, view.format_kwarg, view.headers = drf, None, {}
    try:
        view.initial(drf)
        response = Response(json_roundtrip(view.list_body(drf)))
    except Exception as exc:  # noqa: BLE001 - same handling as the API (401 / 403 / password change)
        response = view.handle_exception(exc)
    data = response.data
    return Result(response.status_code, JSONRenderer().render(data))
