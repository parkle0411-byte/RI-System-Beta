from contextlib import contextmanager

from django.db import connection, transaction

from ri_system.authz import AuthError
from .models import OperationLock

ADMIN_ACCOUNTS = 'admin_accounts'
PRODUCTION_SOURCES = 'production_sources'


@contextmanager
def monthly_operation(month):
    """Fail immediately on contention, including a month's very first write.

    Callers perform their entire transaction inside this context. Dynamic
    acquisition lets exclusions skip closed months while keeping both the
    source and the selected destination protected through commit/rollback.
    """
    names = []
    def acquire(value):
        name = f"{connection.settings_dict['NAME']}:production:{value}"
        if name in names:
            return
        with connection.cursor() as cursor:
            cursor.execute('SELECT GET_LOCK(%s, 0)', [name])
            acquired = cursor.fetchone()[0]
        if acquired != 1:
            raise AuthError(409, 'operation_busy', 'Someone is operating on this month. Please try again shortly.')
        names.append(name)
    try:
        acquire(month)
        yield acquire
    finally:
        if names:
            with connection.cursor() as cursor:
                for name in reversed(names):
                    cursor.execute('SELECT RELEASE_LOCK(%s)', [name])


@contextmanager
def serialized(*keys):
    """Transaction-owned stable guard; all account paths lock it before people."""
    with transaction.atomic():
        for key in sorted(set(keys)):
            OperationLock.objects.get_or_create(key=key)
            OperationLock.objects.select_for_update().get(pk=key)
        yield
