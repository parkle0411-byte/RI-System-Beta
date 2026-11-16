"""Sort first on the ordering columns only, then load the full rows (2026-11-16 owner decision).

MySQL fails a query with "Out of sort memory" (error 1038) when a single row that has to be sorted is
larger than `sort_buffer_size`: every column the query reads (including large JSON such as a case
payload) travels through the sort buffer. One oversized case, review batch, Audit entry or legacy row
would then break the page for everyone. This also happens when only the key is selected but the
filter reads the JSON (for example `payload__productionReversals__isnull`), so the keys are found in
three steps: filter without sorting, sort the matching keys on the ordering columns alone, then read
the rows by primary key. The result is exactly the plain ordered query.
"""


def sorted_keys(queryset, *ordering, start=None, stop=None):
    """Primary keys of `queryset.order_by(*ordering)[start:stop]`; the sort never reads the large columns.

    A locking (select_for_update) queryset takes its row locks in the first, unsorted step."""
    matching = list(queryset.order_by().values_list("pk", flat=True))
    if not matching:
        return []
    keys = queryset.model._base_manager.using(queryset.db).filter(pk__in=matching).order_by(*ordering).values_list("pk", flat=True)
    if start is not None or stop is not None:
        keys = keys[start:stop]
    return list(keys)


def sorted_rows(queryset, *ordering, start=None, stop=None):
    """`list(queryset.order_by(*ordering)[start:stop])`, without sorting the full rows.

    select_related / defer / select_for_update on `queryset` are kept."""
    keys = sorted_keys(queryset, *ordering, start=start, stop=stop)
    if not keys:
        return []
    found = queryset.order_by().in_bulk(keys)
    return [found[key] for key in keys if key in found]


def sorted_values(queryset, ordering, fields, *, stop=None):
    """`list(queryset.order_by(*ordering).values(*fields)[:stop])`, without sorting the full rows."""
    keys = sorted_keys(queryset, *ordering, stop=stop)
    if not keys:
        return []
    pk_name = queryset.model._meta.pk.attname
    extra = () if pk_name in fields else (pk_name,)
    found = {row[pk_name]: row for row in queryset.order_by().filter(pk__in=keys).values(*fields, *extra)}
    rows = [found[key] for key in keys if key in found]
    if extra:
        for row in rows:
            row.pop(pk_name)
    return rows
