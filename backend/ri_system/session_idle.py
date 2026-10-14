"""Human-activity idle policy shared by the SPA, APIs and read-only admin site."""
from datetime import datetime, timezone as dt_timezone
import math
import time
import uuid

from django.conf import settings
from django.contrib.auth import logout
from django.http import JsonResponse

LAST_ACTIVITY = '_ri_last_user_activity'
SESSION_ID = '_ri_activity_session_id'


def now_seconds():
    return time.time()


def start_idle_session(request, *, now=None):
    instant = now_seconds() if now is None else now
    request.session[SESSION_ID] = uuid.uuid4().hex  # Public correlation ID; not an authentication credential.
    touch_idle_session(request, now=instant)
    return session_state(request, now=instant)


def touch_idle_session(request, *, now=None):
    instant = now_seconds() if now is None else now
    request.session[LAST_ACTIVITY] = instant
    deadline = instant + settings.SESSION_IDLE_TIMEOUT_SECONDS
    request.session.set_expiry(datetime.fromtimestamp(deadline, dt_timezone.utc))


def last_activity(request):
    value = request.session.get(LAST_ACTIVITY)
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        return None
    return value


def session_state(request, *, now=None):
    instant = now_seconds() if now is None else now
    previous = last_activity(request)
    if previous is None:
        return None
    return {'id': request.session.get(SESSION_ID),
            'expiresAt': round((previous + settings.SESSION_IDLE_TIMEOUT_SECONDS) * 1000),
            'serverNow': round(instant * 1000),
            'timeoutSeconds': settings.SESSION_IDLE_TIMEOUT_SECONDS,
            'warningSeconds': settings.SESSION_IDLE_WARNING_SECONDS}


class IdleSessionMiddleware:
    """Reads never renew the idle deadline. Expired cookies cannot revive a session."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            now = now_seconds()
            previous = last_activity(request)
            if previous is None or not request.session.get(SESSION_ID):
                # Existing eight-hour sessions adopt this policy on their next authenticated request.
                start_idle_session(request, now=now)
            elif now >= previous + settings.SESSION_IDLE_TIMEOUT_SECONDS:
                logout(request)
                response = JsonResponse({'error': 'SESSION_IDLE_TIMEOUT',
                    'message': 'You were signed out after 3 hours of inactivity.'}, status=401)
                response['Cache-Control'] = 'no-store, max-age=0'
                return response
        response = self.get_response(request)
        if request.user.is_authenticated:
            state = session_state(request)
            if state is not None:
                for header, field in [('X-RI-Session-Id', 'id'), ('X-RI-Session-Expires-At', 'expiresAt'),
                                      ('X-RI-Server-Time', 'serverNow'), ('X-RI-Session-Timeout', 'timeoutSeconds'),
                                      ('X-RI-Session-Warning', 'warningSeconds')]:
                    response[header] = str(state[field])
        return response
