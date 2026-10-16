"""Preview and apply only the expressly approved, unprocessed accounting repairs."""
import hashlib,json
from collections import defaultdict
from django.core.management.base import BaseCommand,CommandError
from django.utils import timezone
from coordination.services import serialized,PRODUCTION_SOURCES
from audit.services import record_snapshot,record_audit,CLI_ACTOR
from audit.models import EntitySnapshot
from cases.models import Case
from cases.accounting_migration import repair_payload
from production.models import ProductionReport
from fxrates.models import FxRate

class Command(BaseCommand):
    help='Preview Review-92 repairs. --apply requires the exact preview signature; closed reports and handled amounts are preserved.'
    def add_arguments(self,parser):
        parser.add_argument('--apply',action='store_true')
        parser.add_argument('--expected-signature')
    def handle(self,*args,**options):
        with serialized(PRODUCTION_SOURCES):
            cases=list(Case.objects.select_for_update().filter(recycled_at__isnull=True,is_archived=False,status__in=('posted','closed','reversed')).select_related('parent_case').order_by('id'))
            reports=list(ProductionReport.objects.filter(status='closed').values('year_month','rows','closed_at','report_uid','row_version'))
            rates=list(FxRate.objects.values('year_month','currency','rate','row_version'))
            signature=hashlib.sha256(json.dumps({'cases':[(str(c.case_uid),c.row_version,c.payload) for c in cases],'reports':reports,'rates':rates},sort_keys=True,default=str).encode()).hexdigest()
            if options['apply'] and options['expected_signature']!=signature:raise CommandError('Preview changed. Run without --apply and review its new signature first.')
            chains=defaultdict(list)
            for case in cases:chains[case.parent_case_id or case.pk].append(case)
            fx={(r['year_month'],r['currency']):r['rate'] for r in rates}
            closed={r['year_month'] for r in reports};result={'signature':signature,'applied':bool(options['apply']),'eligibleCases':len(cases),'changedCases':0,'changes':[],'pending':[]}
            for case in cases:
                snaps=list(EntitySnapshot.objects.filter(entity_type='case',entity_id=str(case.case_uid)).order_by('entity_version').values('snapshot_data','snapshot_reason','entity_version','created_at')) if case.payload.get('claims') else []
                payload,status,changes,pending=repair_payload(case,chains[case.parent_case_id or case.pk],reports,closed,fx,snaps)
                result['pending'].extend({'caseUid':str(case.case_uid),**p} for p in pending)
                if not changes:continue
                result['changedCases']+=1;result['changes'].append({'caseUid':str(case.case_uid),'changes':changes})
                if not options['apply']:continue
                before={'status':case.status,'rowVersion':case.row_version,'payload':case.payload}
                payload.setdefault('accountingAdjustmentHistory',[]).append({'reason':'Owner-approved 92 accounting decisions','changedAt':timezone.now().isoformat(),'changedBy':CLI_ACTOR['id'],'changes':changes})
                case.payload=payload;case.status=status;case.row_version+=1;case.updated_by=CLI_ACTOR['id'];case.save()
                after={'caseUid':str(case.case_uid),'twRef':case.tw_ref,'status':case.status,'rowVersion':case.row_version,'payload':payload}
                record_snapshot(entity_type='case',entity_id=case.case_uid,version=case.row_version,reason='accounting_review_92_applied',data=after,created_by=CLI_ACTOR['id'])
                record_audit(entity_type='case',entity_id=case.case_uid,action='accounting_review_92_applied',before=before,after=after,actor=CLI_ACTOR,source='cli')
            self.stdout.write(json.dumps(result,ensure_ascii=False,default=str))
