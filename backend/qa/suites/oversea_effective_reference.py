"""Effective-date allocation and guarded historical reference correction."""
from pathlib import Path
exec(Path('/app/qa/suites/oversea_business.py').read_text().split('try:\n with transaction.atomic():')[0])
from contextlib import contextmanager
from datetime import date
from io import StringIO
from unittest.mock import patch
from django.core.management import call_command
from django.core.management.base import CommandError
from audit.models import EntitySnapshot
from cases.models import ReferenceSequence, CaseDocument, FinanceReconciliationBatch
from cases.manual_reference import reference_in_use
from cases.workflow import build_endorsement_payload
from cases.oversea_reference_correction import preview_reference_correction as preview, apply_reference_correction as apply
from production.models import ProductionReport
from reminders.models import PaymentAlert
from reminders.runner import run_payment
import uuid

@contextmanager
def temporary_state():
 with transaction.atomic():
  try:yield
  finally:transaction.set_rollback(True)

def rejected(label, function):
 try:function()
 except ValueError:check(label,True)
 else:raise AssertionError(label)

try:
 with transaction.atomic():
  sales,person=account('sales','sales');finance,_=account('finance','accounting')
  for typ,name,code in [('class','Fine Art','FA'),('foreign_broker','Oversea QA Broker',None),('reinsured','Oversea QA Cedant',None)]:MasterRecord.objects.create(entity_type=typ,name=name,code=code,payload={},created_by='qa',updated_by='qa')
  old='TWFA2604001';new='TWFA2601001'
  raw=fixture(currency='USD',originalInsured='Yageo Group QA',ownerPersonnelId=person.pk,ae=person.name,
              policyFrom='2026-01-01',policyTo='2027-01-01',receiptPaymentDate='2026-05-01',
              installmentEnabled=True,performanceInstallments=[dict(id='I1',ratio=50,paymentBaseDate='2026-05-01'),dict(id='I2',ratio=50,paymentBaseDate='2026-08-01')],
              reinsurers=[dict(name='Oversea QA Broker',sharePct=25,brokerageAmount=100)])
  p=normalize_draft(raw)['value'];p.update(twRef=old,status='posted',remark='Original broker wording '+old)
  refresh_transactions(p,old,'2026-11-01T00:00:00Z')
  root=Case.objects.create(tw_ref=old,payload=p,status='posted',reinsurance_structure='OVERSEA',currency='USD',effective_date=date(2026,1,1),expiration_date=date(2027,1,1),owner_personnel=person,row_version=6,created_by='qa',updated_by='qa')
  child_p=build_endorsement_payload(p,old,0)
  child=Case.objects.create(parent_case=root,payload=child_p,case_kind='endorsement',status='draft',reinsurance_structure='OVERSEA',currency='USD',effective_date=date(2026,1,1),owner_personnel=person,created_by='qa',updated_by='qa')
  ReferenceSequence.objects.create(prefix='TWFA2604',last_value=1)
  history=EntitySnapshot.objects.create(entity_type='case',entity_id=str(root.case_uid),entity_version=5,snapshot_reason='announced',snapshot_data={'twRef':old,'payload':copy.deepcopy(p)},created_by='qa')
  historical=copy.deepcopy(history.snapshot_data)
  alert=PaymentAlert.objects.create(case=root,alert_date=date(2026,11,10),alert_kind='weekly_overdue',
      schedule_keys=['transaction:'+t['txNo'] for t in p['transactions']],recipients=[],status='suppressed',
      subject='Historical reminder '+old,body_html='<p>Original reminder '+old+'</p>')
  historical_alert=copy.deepcopy({'keys':alert.schedule_keys,'subject':alert.subject,'body':alert.body_html})
  document=CaseDocument.objects.create(case=root,kind='broker_credit',filename='Original Credit Note '+old+'.pdf',content_type='application/pdf',byte_size=100,sha256='a'*64,storage_key='qa/note.pdf',uploaded_by='qa')
  before_p=copy.deepcopy(root.payload);before_child=copy.deepcopy(child.payload);txs=copy.deepcopy(p['transactions']);before_snapshots=EntitySnapshot.objects.count()
  check('single-settlement reference uses Effective Date',reference_prefix({**p,'installmentEnabled':False})=='TWFA2601')
  check('installment reference ignores all actual receipt dates',reference_prefix(p)=='TWFA2601' and reference_prefix({**p,'receiptPaymentDate':'2030-08-01'})=='TWFA2601')
  check('missing Effective Date does not fall back to receipt date',reference_prefix({**p,'policyFrom':''}) is None)
  plan=preview(root.case_uid,old)
  check('preview chooses unoccupied January reference',plan['newReference']==new and len(plan['transactionMap'])==2)
  root.refresh_from_db();child.refresh_from_db()
  check('preview does not mutate cases or reserve a sequence',root.payload==before_p and child.payload==before_child and not ReferenceSequence.objects.filter(prefix='TWFA2601').exists() and EntitySnapshot.objects.count()==before_snapshots)
  out=StringIO();call_command('correct_oversea_reference',case_uid=str(root.case_uid),old_reference=old,stdout=out)
  check('management command defaults to read-only preview',json.loads(out.getvalue())['apply'] is False)
  with temporary_state():
   Case.objects.create(payload={'previousTwRefs':[new]},is_archived=True,archived_at=__import__('django.utils.timezone',fromlist=['now']).now(),archived_by='qa',created_by='qa',updated_by='qa')
   check('historical reference reservation prevents target reuse',preview(root.case_uid,old)['newReference']=='TWFA2601002')
   rejected('reviewed occupied target is refused',lambda:preview(root.case_uid,old,new))
  with temporary_state():
   root.payload={**before_p,'paymentEntries':[{'id':'payment-history'}]};root.save(update_fields=['payload'])
   rejected('cash history prevents automatic transaction renumbering',lambda:preview(root.case_uid,old))
  with temporary_state():
   ProductionReport.objects.create(year_month='2026-05',version=1,rows=[{'caseUid':str(root.case_uid),'twRef':old}],source_signature='qa',created_by='qa')
   rejected('Production snapshots are protected from reference rewriting',lambda:preview(root.case_uid,old))
  with temporary_state():
   FinanceReconciliationBatch.objects.create(id=uuid.uuid4(),review_date=date(2026,5,1),currency='USD',party_name='Oversea QA Broker',members=[{'caseUid':str(root.case_uid),'txNo':txs[0]['txNo']}],created_by='qa',created_by_name='QA')
   rejected('finance review history prevents silent signature invalidation',lambda:preview(root.case_uid,old))
  with temporary_state():
   child.row_version+=1;child.save(update_fields=['row_version'])
   rejected('stale linked-Draft preview signature is refused',lambda:apply(root.case_uid,old,new,plan['signature']))
  child.refresh_from_db();root.refresh_from_db()
  with temporary_state():
   child.status='posted';child.tw_ref=old+'-E01';child.save(update_fields=['status','tw_ref'])
   rejected('announced endorsements require a separate complete correction plan',lambda:preview(root.case_uid,old))
  with patch('cases.oversea_reference_correction.record_snapshot',side_effect=RuntimeError('QA snapshot failure')):
   try:apply(root.case_uid,old,new,plan['signature'])
   except RuntimeError:pass
   else:raise AssertionError('snapshot failure must abort correction')
  root.refresh_from_db();child.refresh_from_db()
  check('snapshot failure atomically rolls back root, child and sequence',root.tw_ref==old and root.payload==before_p and child.payload==before_child and not ReferenceSequence.objects.filter(prefix='TWFA2601').exists())
  result=apply(root.case_uid,old,new,plan['signature']);root.refresh_from_db();child.refresh_from_db()
  check('one reviewed correction updates root and linked Draft only',result['changedCaseCount']==2 and root.tw_ref==new and root.row_version==7 and child.row_version==2 and child.tw_ref is None)
  check('every T3 reference keeps its exact suffix',[t['txNo'] for t in root.payload['transactions']]==[new+'-R1-I1-T3',new+'-R1-I2-T3'])
  normalized=copy.deepcopy(root.payload);normalized['twRef']=old;normalized.pop('previousTwRefs',None)
  for i,t in enumerate(normalized['transactions']):t['txNo']=txs[i]['txNo']
  check('all amounts, dates, identifiers and broker wording remain unchanged',normalized==before_p)
  expected_child=copy.deepcopy(before_child);expected_child['twRef']=new;expected_child['parentTwRef']=new
  check('Draft parent reference corrected without changing inherited terms',child.payload==expected_child and child.parent_case_id==root.pk)
  check('old reference reserved permanently and returned for search',reference_in_use(old) and root.payload['previousTwRefs']==[old])
  check('new sequence advances while old sequence remains reserved',ReferenceSequence.objects.get(prefix='TWFA2601').last_value==1 and ReferenceSequence.objects.get(prefix='TWFA2604').last_value==1)
  history.refresh_from_db();document.refresh_from_db()
  check('historical snapshot and external broker note are preserved',history.snapshot_data==historical and document.filename=='Original Credit Note '+old+'.pdf' and document.case_id==root.pk)
  alert.refresh_from_db()
  check('historical reminder content and old transaction keys are preserved',{'keys':alert.schedule_keys,'subject':alert.subject,'body':alert.body_html}==historical_alert)
  with patch('reminders.runner._open_cases',return_value=[root]),patch('reminders.runner._people',return_value=[]),patch('reminders.runner._audit'),patch('reminders.runner._send') as send:
   check('old T3 reminder keys suppress duplicate next-day notices',run_payment('2026-11-11')['dueToday']==0)
   check('old T3 reminder keys preserve the next seven-day due date',run_payment('2026-11-17')['dueToday']==1 and not send.called)
  check('two new correction snapshots retain old-to-new mapping',EntitySnapshot.objects.filter(snapshot_reason='oversea_reference_corrected').count()==2)
  check('repeat apply does not renumber again or consume a sequence',apply(root.case_uid,old,new,plan['signature'])['changedCaseCount']==0 and ReferenceSequence.objects.get(prefix='TWFA2601').last_value==1)
  rows=sales.get('/api/cases').json()['cases'];visible=next(c for c in rows if c['caseUid']==str(root.case_uid))
  check('Account List exposes current and old search reference',visible['twRef']==new and old in visible['previousTwRefs'])
  detail=sales.get('/api/cases?caseUid='+str(child.case_uid)).json()['case']
  check('Draft API returns corrected root reference',detail['payload']['parentTwRef']==new)
  workflow=sales.get('/api/case-workflow?caseUid='+str(child.case_uid)).json()['workflow']
  check('Endorsement chain uses corrected root reference',workflow['root']['twRef']==new and workflow['chain'][0]['twRef']==new)
  accounting=finance.get('/api/accounting?view=list').json()['transactionRows'];own=[r for r in accounting if r['caseUid']==str(root.case_uid)]
  check('Accounting uses corrected root and T3 numbers without duplicating accounts',len(own)==2 and all(r['twRef']==new and r['txNo'].startswith(new+'-') for r in own))
  print(str(len(checks))+' passed Oversea Effective Date and reference correction checks',flush=True)
  raise Done()
except Done:pass
