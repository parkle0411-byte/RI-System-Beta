"""Announce late production into the first open month without rewriting policy dates.

The caller holds PRODUCTION_SOURCES through commit, as do report closes and
manual exclusions. Thus the chosen destination cannot close during this write.
"""
import re

from audit.services import record_audit
from ri_system.authz import AuthError
from . import calc
from .models import ProductionExclusion, ProductionReport
from .views import case_source, exclusion_row

_MONTH = re.compile(r'^[0-9]{4}-(0[1-9]|1[0-2])$')


def defer_closed_production(case, actor, request_id=None):
    source = case_source(case)
    months = {row['performanceMonth'] for row in calc.installment_allocations(calc.normalize_source(source))}
    closed = set(ProductionReport.objects.filter(status='closed').values_list('year_month', flat=True))
    deferred = []
    for month in sorted(months & closed):
        preview = calc.build_production_preview([source], month, {}, [])
        keys = sorted({row['key'] for row in [*preview['rows'], *preview.get('accountingRows', [])]})
        if not keys:
            continue
        candidate = month
        while True:
            candidate = calc.next_production_month(candidate)
            if not _MONTH.fullmatch(candidate) or candidate <= month:
                raise AuthError(409, 'no_open_month', 'No later open month is available for this announcement.')
            if candidate not in closed:
                break
        for key in keys:
            exclusion = ProductionExclusion.objects.create(
                case=case, year_month=month, scope='case', installment_key=key,
                deferred_to=candidate, reason=f'Automatically deferred because Production month {month} is closed.',
                created_by=actor['name'])
            record_audit(entity_type='production_exclusion', entity_id=exclusion.id, action='auto_defer_production_row',
                before=None, after=exclusion_row(exclusion), actor=actor, request_id=request_id,
                metadata={'month': month, 'caseUid': str(case.case_uid), 'via': 'announce'})
            deferred.append({'fromMonth': month, 'toMonth': candidate, 'installmentKey': key})
    return deferred
