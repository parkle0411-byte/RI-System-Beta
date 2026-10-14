"""Committed, overlapping API writes. DISPOSABLE database only."""
import os
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone as tz
from uuid import uuid4
from unittest import mock
from django.contrib.auth import get_user_model
from django.db import connections
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate
from audit.models import AuditLog, EntitySnapshot
from cases.draft import normalize_draft
from cases.models import Case, CaseDocument
from cases.workflow_views import AnnounceView
from cases.claims_views import ClaimsView
from cases.views import CasesView
from production.models import ProductionReport, ProductionExclusion
from production import views as production

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
User = get_user_model()
from personnel.models import Personnel
tag = uuid4().hex[:8]
user = User.objects.create_user(username='zz.source.'+tag)
principal = Personnel.objects.create(name='ZZ Source '+tag,department='admin',role_code='admin',is_active=True,
    account_status='active',auth_user_id=str(user.pk),created_by='qa',updated_by='qa')
factory = APIRequestFactory()
results = []
def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ')+name+(' '+str(detail) if not ok else ''),flush=True)
def api(view,body,method='post'):
    req = getattr(factory,method)('/',body,format='json')
    force_authenticate(req,user=User.objects.get(pk=user.pk))
    return view.as_view()(req)
helpers = {}
exec(open('qa/suites/production_api.py').read().split('\ntry:\n')[0],helpers)
def case_for(month,status='posted',**extra):
    value = normalize_draft(helpers['ready'](policyFrom=month+'-01',policyTo=str(int(month[:4])+1)+month[4:]+'-01',
        currency='TWD',ownerPersonnelId=principal.pk,**extra))['value']
    return Case.objects.create(tw_ref=('ZZ-SOURCE-'+uuid4().hex[:12]) if status=='posted' else None,owner_personnel=principal,
        status=status,payload=value,currency='TWD',reinsurance_structure='QS',
        announced_at=datetime(2026,1,1,tzinfo=tz.utc) if status=='posted' else None,created_by='qa',updated_by='qa')
def prd(action,month,**extra):
    return api(production.ProductionReportView,dict(action=action,month=month,**extra))
def generate(month):
    response = prd('generate',month,sourceSignature=production.load_month(month)['preview']['sourceSignature'])
    assert response.status_code==201,response.data
    r=response.data['report']
    return r,dict(reportUid=r['reportUid'],rowVersion=r['rowVersion'],sourceSignature=r['sourceSignature'])
def docs_for(case):
    return [str(CaseDocument.objects.create(case=case,kind=kind,reinsurers=names,filename=kind+'.pdf',
        content_type='application/pdf',byte_size=5,sha256='0'*64,storage_key='zz-source-'+uuid4().hex,uploaded_by='qa').pk)
        for kind,names in [('offer',[]),('signed',['ZZ Re A']),('confirmation',['ZZ Re B'])]]
def announce(case,docs=None):
    return api(AnnounceView,dict(caseUid=str(case.case_uid),rowVersion=case.row_version,confirmed=True,
        documentIds=docs if docs is not None else docs_for(case)))
def threaded(fn):
    try:return fn()
    finally:connections.close_all()
def after_read(first,second):
    held,release=threading.Event(),threading.Event()
    original=production.load_month
    ident=[]
    def hook(*a,**kw):
        value=original(*a,**kw)
        if threading.get_ident()==ident[0] and not held.is_set():
            held.set();assert release.wait(20)
        return value
    def one():
        ident.append(threading.get_ident());return threaded(first)
    with mock.patch('production.views.load_month',side_effect=hook),ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(one);assert held.wait(15)
        try:two=second()
        finally:release.set()
        return future.result(timeout=30),two
def close_fixture(month):
    case=case_for(month);report,body=generate(month)
    return case,report,body

with override_settings(AUDIT_LOG_PAUSED=True):
    audit_before=AuditLog.objects.count()
    month=timezone.localtime(timezone.now(),timezone.get_fixed_timezone(480)).strftime('%Y-%m')
    existing,report,body=close_fixture(month)
    added=case_for(month,'draft');docs=docs_for(added)
    before_snapshots=EntitySnapshot.objects.count()
    close,announced=after_read(lambda:prd('close',month,**body),lambda:announce(added,docs))
    check('concurrent Announce succeeds before closing finishes',announced.status_code==200,announced.data)
    check('closing rejects newly announced source',close.status_code==409 and close.data.get('error')=='source_changed',close.data)
    existing.refresh_from_db();added.refresh_from_db()
    check('failed close leaves old and new cases posted',existing.status=='posted' and existing.row_version==1 and added.status=='posted')
    check('failed close leaves report valid and no close snapshots',ProductionReport.objects.get(report_uid=report['reportUid']).status=='valid'
        and EntitySnapshot.objects.filter(snapshot_reason='production_case_confirmed',entity_id__in=[str(existing.case_uid),str(added.case_uid)]).count()==0)
    report,body=generate(month);closed=prd('close',month,**body)
    check('regenerated report includes new case and closes',closed.status_code==200 and any(r['caseUid']==str(added.case_uid) for r in report['rows']),closed.data)

    # Both the existing closed month and its next month are closed.
    next_month=production.calc.next_production_month(month)
    ProductionReport.objects.create(year_month=next_month,version=1,status='closed',rows=[],source_signature='[]',created_by='qa',closed_by='qa',closed_at=timezone.now(),close_token=uuid4())
    late=case_for(month,'draft');late_response=announce(late)
    late.refresh_from_db()
    destination=production.calc.next_production_month(next_month)
    check('late Announce succeeds and reports first open month',late_response.status_code==200
        and late_response.data.get('productionDeferrals',[{}])[0].get('toMonth')==destination,late_response.data)
    e=list(ProductionExclusion.objects.filter(case=late))
    check('late Announce creates one case exclusion for FULL',len(e)==1 and e[0].year_month==month and e[0].deferred_to==destination)
    check('late Announce preserves original policy dates',late.payload['policyFrom']==month+'-01')
    check('late source is excluded from closed month',not any(r['caseUid']==str(late.case_uid) for r in production.load_month(month)['preview']['rows']))
    check('late source appears in open destination',any(r['caseUid']==str(late.case_uid) for r in production.load_month(destination)['preview']['rows']))
    check('closed report rows remain unchanged',ProductionReport.objects.get(report_uid=report['reportUid']).rows==report['rows'])

    # Incoming auto deferral also invalidates a close already preparing the destination.
    report,body=generate(destination)
    another=case_for(month,'draft');docs=docs_for(another)
    close,announced=after_read(lambda:prd('close',destination,**body),lambda:announce(another,docs))
    check('incoming automatic deferral succeeds while destination is closing',announced.status_code==200,announced.data)
    check('incoming automatic deferral forces destination re-preview',close.status_code==409 and close.data.get('error')=='source_changed',close.data)

    # Existing source edits must be checked, including excluded cases with no close plans.
    m='2094-03';case,report,body=close_fixture(m)
    payload=dict(case.payload,originalInsured='Changed during close')
    close,edit=after_read(lambda:prd('close',m,**body),lambda:api(CasesView,dict(caseUid=str(case.case_uid),rowVersion=case.row_version,case=payload),'put'))
    check('existing source edit succeeds during close preparation',edit.status_code==200,edit.data)
    check('existing source edit rejects close',close.status_code==409 and close.data.get('error')=='source_changed',close.data)
    case.refresh_from_db();state=production.load_month(m)
    excluded=prd('exclude',m,scope='case',reason='QA',rowId=state['preview']['rows'][0]['id'])
    assert excluded.status_code==201,excluded.data
    report,body=generate(m)
    close,claim=after_read(lambda:prd('close',m,**body),lambda:api(ClaimsView,dict(action='create_claim',caseUid=str(case.case_uid),
        rowVersion=case.row_version,claim=dict(dateOfLoss='2026-01-01',outstandingReserve=100))))
    check('excluded source claim succeeds during close preparation',claim.status_code==200,claim.data)
    check('excluded source change rejects close even without included cases',close.status_code==409 and close.data.get('error')=='source_changed',close.data)
    check('excluded source report remains valid',ProductionReport.objects.get(report_uid=report['reportUid']).status=='valid')

    # Multiple installments and year boundary; no changes to financial amounts.
    for m in ['2092-12','2093-01']:
        ProductionReport.objects.create(year_month=m,version=1,status='closed',rows=[],source_signature='[]',created_by='qa',closed_by='qa',closed_at=timezone.now(),close_token=uuid4())
    instal=case_for('2092-12','draft',installmentEnabled=True,performanceInstallments=[
        dict(id='I1',performanceMonth='2092-12',paymentBaseDate='2092-12-01',premium=600),dict(id='I2',performanceMonth='2093-01',paymentBaseDate='2093-01-01',premium=400)])
    response=announce(instal)
    moves=response.data.get('productionDeferrals',[])
    check('multiple closed installments defer to first open year-crossing month',response.status_code==200 and len(moves)==2
        and {x['toMonth'] for x in moves}=={'2093-02'},response.data)
    rows=[r for r in production.load_month('2093-02')['preview']['rows'] if r['caseUid']==str(instal.case_uid)]
    check('deferred installments preserve both installment keys',len({r['key'] for r in rows})==2)
    check('deferral changes no stored premiums',Case.objects.get(pk=instal.pk).payload['originalPremium']==1000)

    # Impossible future destination: all Announce writes (including sequence) roll back.
    ProductionReport.objects.create(year_month='9999-12',version=1,status='closed',rows=[],source_signature='[]',created_by='qa',closed_by='qa',closed_at=timezone.now(),close_token=uuid4())
    last=case_for('9998-12','draft');last.payload['policyFrom']='9999-12-01';last.payload['policyTo']='9999-12-31';last.save()
    docs=docs_for(last);snap_before=EntitySnapshot.objects.count()
    response=announce(last,docs);last.refresh_from_db()
    check('no representable future month rejects announcement',response.status_code==409 and response.data.get('error')=='no_open_month',response.data)
    check('failed auto deferral keeps draft reference and snapshot unchanged',last.status=='draft' and last.tw_ref is None
        and EntitySnapshot.objects.count()==snap_before and not ProductionExclusion.objects.filter(case=last).exists())
    check('Audit remains paused',AuditLog.objects.count()==audit_before)

print(f'{sum(results)}/{len(results)} passed',flush=True)
assert all(results),results
