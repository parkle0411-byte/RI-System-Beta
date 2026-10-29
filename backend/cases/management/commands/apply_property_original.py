"""Adopt the approved Original rules only where accounting history permits it."""
import copy
import json
from django.core.management.base import BaseCommand
from django.utils import timezone
from coordination.services import PRODUCTION_SOURCES, serialized
from audit.services import record_snapshot
from cases.models import Case
from cases.property_original import (scope, ordinary, eligible, VERSION_KEY, VERSION,
    refresh_transactions, persist_settlements)


class Command(BaseCommand):
    help = 'Preview eligible Property / QS / PD Original conversion; --apply persists it.'

    def add_arguments(self, parser):
        parser.add_argument('--apply',action='store_true')

    def handle(self,*args,**options):
        totals={'eligible':0,'historical':0,'facility':0,'alreadyVersioned':0,'changed':0,'apply':options['apply']}
        with serialized(PRODUCTION_SOURCES):
            cases=Case.objects.select_for_update().filter(parent_case__isnull=True,is_archived=False,recycled_at__isnull=True).order_by('pk')
            for case in cases:
                p=case.payload if isinstance(case.payload,dict) else {}
                if not scope(p):continue
                if p.get(VERSION_KEY):totals['alreadyVersioned']+=1;continue
                if not ordinary(p):totals['facility']+=1;continue
                can_adopt=case.status in ('draft','posted') and eligible(p) and not p.get('paymentEntries')
                totals['eligible' if can_adopt else 'historical']+=1
                if not options['apply']:continue
                before=copy.deepcopy(p);p=copy.deepcopy(p)
                p[VERSION_KEY]=VERSION if can_adopt else 'historical'
                for index,r in enumerate(p.get('performanceInstallments') or []):
                    r.setdefault('paymentBaseDateManual',bool(index==0 and r.get('paymentBaseDate')!=p.get('policyFrom')))
                    r.setdefault('performanceMonthManual',r.get('performanceMonth')!=str(r.get('paymentBaseDate') or '')[:7])
                if can_adopt and case.status=='posted':
                    stamp=timezone.now().isoformat()
                    p.update(twRef=case.tw_ref,announcedAt=case.announced_at.isoformat() if case.announced_at else stamp)
                    refresh_transactions(p,stamp);persist_settlements(p,stamp)
                case.payload=p;case.row_version+=1;case.updated_by='system:property-original-rules';case.save()
                record_snapshot(entity_type='case',entity_id=case.case_uid,version=case.row_version,
                    reason='property_original_rules_adopted' if can_adopt else 'property_accounting_history_preserved',
                    data={'caseUid':str(case.case_uid),'twRef':case.tw_ref,'status':case.status,'payload':p,
                          'previousAccountingVersion':before.get(VERSION_KEY)},created_by='system:property-original-rules')
                totals['changed']+=1
        self.stdout.write('RESULT '+json.dumps(totals,sort_keys=True))
