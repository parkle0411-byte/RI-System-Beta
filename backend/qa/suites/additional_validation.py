"""Closed-month FX and signed claim amounts; every fixture rolls back."""
import os
from uuid import uuid4
from datetime import datetime, timezone
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import override_settings
from rest_framework.test import APIRequestFactory, force_authenticate
from audit.models import AuditLog, EntitySnapshot
from cases.models import Case
from cases.draft import normalize_draft
from cases.claims_views import ClaimsView
from fxrates.models import FxRate, CURRENCIES
from fxrates.views import FxRatesView
from personnel.models import Personnel
from production import views as production
from production.models import ProductionReport

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
results=[]
def check(name,ok,detail=''):
    results.append(bool(ok));print(('PASS ' if ok else 'FAIL ')+name+(' '+str(detail) if not ok else ''),flush=True)
class Rollback(Exception): pass
factory=APIRequestFactory()
User=get_user_model()
try:
    with transaction.atomic(),override_settings(AUDIT_LOG_PAUSED=True):
        tag=uuid4().hex[:8];user=User.objects.create_user(username='zz.addval.'+tag)
        principal=Personnel.objects.create(name='ZZ Addval '+tag,department='admin',role_code='admin',is_active=True,
            auth_user_id=str(user.pk),account_status='active',created_by='qa',updated_by='qa')
        def api(view,body,method='post'):
            req=getattr(factory,method)('/',body,format='json');force_authenticate(req,user=user);return view.as_view()(req)
        helpers={};exec(open('qa/suites/production_api.py').read().split('\ntry:\n')[0],helpers)
        def case_for(month):
            payload=normalize_draft(helpers['ready'](currency='TWD',ownerPersonnelId=principal.pk,policyFrom=month+'-01',
                policyTo=str(int(month[:4])+1)+month[4:]+'-01'))['value']
            return Case.objects.create(status='posted',tw_ref='ZZ-ADDVAL-'+uuid4().hex[:12],payload=payload,
                currency='TWD',reinsurance_structure='QS',announced_at=datetime(2026,1,1,tzinfo=timezone.utc),created_by='qa',updated_by='qa')
        def close_month(month):
            signature=production.load_month(month)['preview']['sourceSignature']
            r=api(production.ProductionReportView,dict(action='generate',month=month,sourceSignature=signature))
            assert r.status_code==201,r.data
            report=r.data['report']
            r=api(production.ProductionReportView,dict(action='close',month=month,sourceSignature=signature,
                reportUid=report['reportUid'],rowVersion=report['rowVersion']))
            assert r.status_code==200,r.data
            return report
        def fx_body(month):
            current={r.currency:r for r in FxRate.objects.filter(year_month=month)}
            return dict(yearMonth=month,rates=[dict(currency=c,rate=30 if c=='USD' else 1,
                rowVersion=current[c].row_version if c in current else None) for c in CURRENCIES])
        audit_before=AuditLog.objects.count()
        case_for('2096-05');close_month('2096-05')
        before=EntitySnapshot.objects.count();r=api(FxRatesView,fx_body('2096-05'))
        check('closed TWD month rejects first six FX rates',r.status_code==409 and r.data.get('error')=='month_locked',r.data)
        check('rejected FX creates no rates or snapshots',not FxRate.objects.filter(year_month='2096-05').exists() and EntitySnapshot.objects.count()==before)
        req=factory.get('/?month=2096-05');force_authenticate(req,user=user);r=production.ProductionReportView.as_view()(req)
        check('closed month scope reports FX locked even without rate rows',r.data['scope']['monthClosed'] and r.data['scope']['fxLocked'])
        close_month('2096-06');r=api(FxRatesView,fx_body('2096-06'))
        check('closed empty month also rejects first FX set',r.status_code==409 and r.data.get('error')=='month_locked',r.data)
        r=api(FxRatesView,fx_body('2096-07'))
        check('open month accepts first FX set',r.status_code in (200,201),r.data)
        close_month('2096-07')
        FxRate.objects.filter(year_month='2096-07').update(is_locked=False,locked_by=None,locked_at=None,lock_reason=None)
        before=list(FxRate.objects.filter(year_month='2096-07').values_list('rate','row_version'));r=api(FxRatesView,fx_body('2096-07'))
        check('closed report is authoritative even if existing FX rows are unlocked',r.status_code==409 and r.data.get('error')=='month_locked',r.data)
        check('closed unlocked FX values and versions stay unchanged',before==list(FxRate.objects.filter(year_month='2096-07').values_list('rate','row_version')))

        case=case_for('2096-08')
        # 2026-10-16「92 項會計規則重新確認」：賠款按出險日適用的保單／批單比例分攤；出險日不在任何保單期間回 409 claim_split_pending_review。
        # 原 fixture 出險日 2026-01-01 不在保單期間（2096-08-01～2097-08-01），改放在保單期間內，其餘斷言不變。
        DOL='2096-09-01'
        def claim(action,**extra):
            case.refresh_from_db()
            return api(ClaimsView,dict(caseUid=str(case.case_uid),rowVersion=case.row_version,action=action,**extra))
        for value in ['1e308','-1e308']:
            before=(case.row_version,case.payload,EntitySnapshot.objects.count())
            r=claim('create_claim',claim=dict(dateOfLoss=DOL,outstandingReserve=value));case.refresh_from_db()
            check('unrepresentable/negative reserve rejected '+value,r.status_code==400 and r.data.get('error')=='invalid_claim_reserve',r.data)
            check('rejected reserve leaves case/version/snapshots unchanged '+value,before==(case.row_version,case.payload,EntitySnapshot.objects.count()))
        r=claim('create_claim',claim=dict(dateOfLoss=DOL,outstandingReserve=12.345));case.refresh_from_db()
        check('valid reserve rounds to two decimals',r.status_code==200 and case.payload['claims'][0]['outstandingReserve']==12.35,r.data)
        before=(case.row_version,case.payload,EntitySnapshot.objects.count())
        r=claim('update_reserve',claimId=1,outstandingReserve='1e308');case.refresh_from_db()
        check('updating reserve also rejects rounding overflow',r.status_code==400 and r.data.get('error')=='invalid_claim_reserve',r.data)
        check('failed reserve update leaves case/version/snapshots unchanged',before==(case.row_version,case.payload,EntitySnapshot.objects.count()))
        r=claim('update_reserve',claimId=1,outstandingReserve=0.001);case.refresh_from_db()
        check('zero reserve after rounding remains valid',r.status_code==200 and case.payload['claims'][0]['outstandingReserve']==0,r.data)
        for value in ['1e308','-1e308',0.001,0.004]:
            before=(case.row_version,case.payload,EntitySnapshot.objects.count())
            r=claim('record_payment',claimId=1,payment=dict(date='2026-01-02',amount=value));case.refresh_from_db()
            check('unrepresentable/rounded zero payment rejected '+str(value),r.status_code==400,r.data)
            check('rejected claim payment creates no payment/transaction/snapshot '+str(value),before==(case.row_version,case.payload,EntitySnapshot.objects.count()))
        for value,expected in [(12.345,12.35),(-12.34,-12.34),(100.005,100.01)]:
            r=claim('record_payment',claimId=1,payment=dict(date='2026-01-02',amount=value));case.refresh_from_db()
            check('signed claim payment keeps existing rounding '+str(value),r.status_code==200 and case.payload['claims'][0]['payments'][-1]['amount']==expected,r.data)
            check('valid signed payment builds nonzero claim transactions '+str(value),any(t['amount']!=0 for t in case.payload['transactions'][-4:]))
        r=claim('update_reserve',claimId=1,outstandingReserve='1e306');case.refresh_from_db()
        check('no new amount cap introduced for a finite rounded reserve',r.status_code==200 and case.payload['claims'][0]['outstandingReserve']==1e306,r.data)
        check('Audit remains paused',AuditLog.objects.count()==audit_before)
        raise Rollback()
except Rollback:pass
print(f'{sum(results)}/{len(results)} passed; database changes rolled back',flush=True)
assert all(results),results
