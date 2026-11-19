"""Keep the settled legacy history warm in every web worker (2026-11-17 owner decision; 2026-11-19 extended).

All Accounts' first load used to rebuild the settled legacy history in the request (about 11 seconds for
6,094 rows, once per worker, after every restart, import or Taipei midnight). Each gunicorn worker now runs
one background thread that rebuilds it before anyone asks:
- at worker start;
- when the history changes (cheap signature: count, max key, version sum, latest update time), checked every
  30 seconds, and at once in the worker that has just committed a web import (poke());
- when the Taipei date changes (only needed for sort keys of a history with unsettled rows; a settled history
  keeps its part and sort keys).
2026-11-19: it also builds the sort keys of all three tabs and, while the Accounting screen is in use (a page
request within the last 10 minutes), does the once-a-minute content check, so requests do not wait for it.
The heavy calculation itself is shared through legacy.ledger's snapshot file and the converted part through
cases.accounting_pages' snapshot file, so only one worker computes and the others read the result. The thread
only reads: it builds the same caches the first request would build. RI_LEGACY_HISTORY_WARM=false switches it off.
"""
import logging
import os
import sys
import threading
import time

log = logging.getLogger(__name__)
INTERVAL = 30
ACTIVE_SECONDS = 600
_started = False
_wake = threading.Event()


def enabled():
    return os.environ.get('RI_LEGACY_HISTORY_WARM', 'true').strip().lower() != 'false'


def in_web_worker():
    return 'gunicorn' in os.path.basename(sys.argv[0] if sys.argv else '')


def poke():
    """Wake this worker's warm-up now (after a web import has been committed)."""
    _wake.set()


def warm_once(max_age=None):
    """Build this worker's Accounting history part and sort keys exactly as the first All Accounts requests would."""
    from django.test import RequestFactory
    from rest_framework.request import Request
    from cases import accounting_pages
    from cases.accounting_views import AccountingView
    request = Request(RequestFactory().get('/api/accounting', {'view': 'options'}))
    request.ri_principal = None   # no user: the history part never depends on who asks (scope is computed, not used)
    accounting_pages.warm_history(AccountingView(), request, accounting_pages.RECHECK_SECONDS if max_age is None else max_age)


def _state():
    import legacy.ledger as ledger
    from cases.accounting_pages import _cheap_signature
    return ledger._today(), _cheap_signature(ledger)


def _loop():
    from django.db import connections
    from cases import accounting_pages
    time.sleep(3)   # let the worker finish booting
    last = None
    failing = False
    while True:
        try:
            state = _state()
            if state != last:
                started = time.monotonic()
                warm_once()
                last = state
                log.info('Legacy history warm-up done in %.1fs', time.monotonic() - started)
            elif accounting_pages.recently_used(ACTIVE_SECONDS):
                warm_once(max_age=accounting_pages.RECHECK_SECONDS - INTERVAL / 2)   # minute content check, off the request
            failing = False
        except Exception:   # never let the warm-up affect the worker; the first request still builds it
            if not failing:   # log the first failure of a run only (e.g. the database is not reachable yet)
                log.exception('Legacy history warm-up failed; retrying every %ss', INTERVAL)
            failing = True
        finally:
            connections.close_all()
        _wake.wait(INTERVAL)
        _wake.clear()


def start():
    global _started
    if _started or not enabled() or not in_web_worker():
        return
    _started = True
    threading.Thread(target=_loop, name='legacy-history-warm', daemon=True).start()
