"""Disposable regression for endorsement performance and closed-month deferral."""

import os
import uuid
from datetime import datetime, timezone

from django.db import transaction

from cases.models import Case
from production.calc import base_month, build_production_preview
from production.deferrals import defer_closed_production
from production.models import ProductionExclusion, ProductionReport
from production.views import case_source, exclusion_row


assert os.environ.get('RI_DISPOSABLE_QA') == 'true'


def check(label, condition):
    assert condition, label
    print('PASS ' + label, flush=True)


class Rollback(Exception):
    pass


def closed_report(month):
    return ProductionReport.objects.create(
        year_month=month, version=1, status='closed', rows=[{'original': month}], excluded_rows=[],
        source_signature='historical-' + month, created_by='qa', closed_by='qa',
        closed_at=datetime(2046, 8, 1, tzinfo=timezone.utc), close_token=uuid.uuid4())


try:
    with transaction.atomic():
        root_payload = {
            'policyFrom': '2046-03-01', 'policyTo': '2047-03-01', 'currency': 'TWD',
            'originalPremium': 10000, 'riCommPct': 10, 'taxPct': 0,
            'reinsurers': [{'name': 'QA Re', 'sharePct': 100, 'premium': 8000, 'riCommPct': 5, 'taxPct': 0}],
        }
        root = Case.objects.create(case_kind='original', status='posted', tw_ref='QA-PM-ROOT',
                                   payload=root_payload, created_by='qa', updated_by='qa')
        original = {
            **root_payload, 'parentTwRef': root.tw_ref, 'endoEffectiveDate': '2046-06-24',
            'originalPremium': 500, 'reinsurers': [
                {'name': 'QA Re', 'sharePct': 100, 'premium': 400, 'riCommPct': 5, 'taxPct': 0}],
        }
        add = Case.objects.create(case_kind='endorsement', parent_case=root, status='posted',
                                  tw_ref='QA-PM-ROOT-E01', payload=original,
                                  created_by='qa', updated_by='qa')
        source = case_source(add)
        check('endorsement uses its June effective month, not March policy inception',
              base_month(source['payload']) == '2046-06')
        check('March and April previews cannot include a June endorsement',
              all(not build_production_preview([source], month)['rows'] for month in ('2046-03', '2046-04')))
        check('open effective month includes the endorsement',
              len(build_production_preview([source], '2046-06')['rows']) == 1)
        check('original policy keeps its own inception-month rule',
              base_month(root_payload) == '2046-03')
        check('legacy case-specific performance override remains intact',
              base_month({**original, 'endorsementPerformanceMonth': '2046-09'}) == '2046-09')

        may = closed_report('2046-05')
        june = closed_report('2046-06')
        july = closed_report('2046-07')
        before = [list(ProductionReport.objects.filter(pk=report.pk).values())[0]
                  for report in (may, june, july)]
        deferred = defer_closed_production(add, {'id': 'qa', 'name': 'QA'})
        check('closed effective month skips the next closed month',
              len(deferred) == 1 and deferred[0]['fromMonth'] == '2046-06'
              and deferred[0]['toMonth'] == '2046-08')
        check('no premature March or May exclusion is created',
              list(ProductionExclusion.objects.filter(case=add).values_list('year_month', flat=True)) == ['2046-06'])
        exclusions = [exclusion_row(row) for row in ProductionExclusion.objects.filter(case=add)]
        check('August preview includes the deferred endorsement exactly once',
              len(build_production_preview([source], '2046-08', {}, exclusions)['rows']) == 1)
        check('closed reports remain byte-for-byte intact',
              before == [list(ProductionReport.objects.filter(pk=report.pk).values())[0]
                         for report in (may, june, july)])

        reduction = {**original, 'endoEffectiveDate': '2046-11-21', 'originalPremium': -100,
                     'reinsurers': [{**original['reinsurers'][0], 'premium': -80}]}
        check('negative-premium endorsement also starts in its November effective month',
              base_month(reduction) == '2046-11')
        check('old-month preview excludes future negative premium',
              not build_production_preview([{'id': 12345, 'status': 'posted', 'payload': reduction}], '2046-08')['rows'])
        raise Rollback()
except Rollback:
    pass

print('11/11 endorsement Production month checks passed; database changes rolled back', flush=True)
