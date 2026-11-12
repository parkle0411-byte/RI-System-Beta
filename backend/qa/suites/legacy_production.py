"""FX arrival/correction, original currency independence and immutable closed reports."""
from pathlib import Path
exec(Path('/app/qa/suites/legacy_entries.py').read_text().replace("print(f'{len(checks)}/{len(checks)} passed')",'pass'))
from fxrates.models import FxRate
from production.models import ProductionReport
month='2035-02';admin=clients['admin']
def prod(action=None,want=200,**body):
    r=admin.get('/api/production-report?month='+month) if action is None else admin.post('/api/production-report',json.dumps(dict(action=action,month=month,**body)),content_type='application/json')
    check('Production '+str(action)+' '+str(want),r.status_code==want,r.content[:1200]);return r.json()
# 2026-11-12: currency, Share and the AE/Sub AE split follow the source; Revenue Month is automatic.
psrc=make_source('PROD-REF',currency='USD',share=25,subAe='Entry admin',aePct=40,effectiveDate='2035-01-01',expiryDate='2035-12-31')
t=create(src=psrc);t=save(t,dict(gross=100.03,commissionRate=15,taxRate=1,brokerage=4.55,effectiveDate='2035-02-10',endorsementNo='E-FX'));t=confirm(t)
check('automatic Revenue Month follows the later effective month',t['revenueMonth']==month,t['revenueMonth'])
preview=prod();check('missing monthly FX is visible',preview['summary']['missingRateCurrencies']==['USD'],preview)
prod('generate',400,sourceSignature=preview['sourceSignature'])
rows=admin.get('/api/accounting?view=list').json()['transactionRows']
check('missing FX does not hide original currency accounts',len([r for r in rows if r.get('caseUid')==t['uid']])==3)
fx=FxRate.objects.create(year_month=month,currency='USD',rate='31.2',created_by='qa',updated_by='qa')
p=prod();ours=[r for r in p['rows'] if r.get('legacyTransactionId')==t['uid']]
check('arriving FX computes both staff shares',len(ours)==2 and sum(r['income'] for r in ours)==142 and [r['income'] for r in ours]==[57,85],ours)
old=p['sourceSignature'];FxRate.objects.filter(pk=fx.pk).update(rate='33',row_version=2)
p=prod();check('unclosed FX correction updates signature and money',p['sourceSignature']!=old and sum(r['income'] for r in p['rows'])==150,p)
prod('generate',409,sourceSignature=old)
generated=prod('generate',201,sourceSignature=p['sourceSignature'])
report=ProductionReport.objects.filter(year_month=month).first()
prod('close',reportUid=str(report.report_uid),rowVersion=report.row_version,sourceSignature=p['sourceSignature'])
report.refresh_from_db();closed=json.dumps(report.rows,sort_keys=True)
record=LegacyTransaction.objects.get(pk=t['uid']);check('closed FX snapshot freezes staff totals',record.fx_snapshot['rate']==33 and record.fx_snapshot['incomeTwd']==150)
FxRate.objects.filter(pk=fx.pk).update(rate='99',row_version=3)
report.refresh_from_db();check('closed report never changes',json.dumps(report.rows,sort_keys=True)==closed)
p=prod();check('closed legacy preview retains the recognized rate',all(r['rate']==33 for r in p['rows']),p)
code,r=send(clients['sales'],dict(id=t['uid'],version=record.version,action='retract'))
check('closed Production blocks retract',code==409,r)
d=create(src=psrc);d=save(d,dict(gross=100,commissionRate=0,taxRate=0,brokerage=1,effectiveDate='2035-02-15',endorsementNo='E-CLOSED'));d=confirm(d)
check('a closed month rolls to the first open month',d['revenueMonth']=='2035-03',d['revenueMonth'])
check('claim transactions never contribute to Production',not any(r.get('legacyTransactionId') in {str(x.uid) for x in LegacyTransaction.objects.filter(data__kind='claim')} for r in p['rows']))
check('Production close creates no native cases',Case.objects.count()==cases)
print(f'{len(checks)}/{len(checks)} passed')
