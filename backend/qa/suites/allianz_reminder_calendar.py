"""Allianz reminder calendar, fixed deadlines, and non-target isolation."""
import calendar,copy,json,os
from datetime import date,timedelta
from unittest.mock import patch
from cases.allianz_accounting import NAME,reminder_date
from cases.calc.payment_terms import build_payment_schedule,add_calendar_days,month_end_date,endorsement_base_date
from cases.calc.accounting import build_premium_transactions
from cases.cash_ledger import transaction_details
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
checks=[]
def check(label,ok,extra=None):
 assert ok,(label,extra)
 checks.append(label)
def raw(**kw):
 p={'twRef':'QA-AZ-CALENDAR','currency':'TWD','classOfBusiness':'Property','reinsuranceStructure':'QS','reinsured':'QA Cedant','policyFrom':'2026-01-01','policyTo':'2027-01-01','paymentTermsDays':90,'originalPremium':1000,'riCommPct':0,'taxPct':0,'reinsurers':[{'name':NAME,'sharePct':100,'premium':800,'riCommPct':0,'taxPct':0,'paymentTermsDays':90}],'paymentEntries':[]}
 p.update(kw);return p
def items(p,today='2026-01-01'):return build_payment_schedule(p,today+'T01:00:00Z')['items']
def target(p,today='2026-01-01'):return next(r for r in items(p,today) if r.get('allianzFacility'))
def oracle(y,m):
 # Count back from the first day of the fourth following month, independently
 # of production's third-month-end implementation.
 future=y*12+m-1+4;return (date(future//12,future%12+1,1)-timedelta(days=11)).isoformat()
def old_dates(p,i):
 source=i.get('baseDate','')
 if p.get('parentTwRef') and p.get('installmentEnabled') is not True:source=endorsement_base_date(p)
 base=month_end_date(source)
 return source,base,add_calendar_days(base,90) if base else '',add_calendar_days(base,80) if base else ''
examples=[('2026-01-31','2026-04-20','2026-05-01'),('2026-02-28','2026-05-21','2026-05-29'),('2028-02-29','2028-05-21','2028-05-29'),('2026-11-30','2027-02-18','2027-02-28'),('2027-11-30','2028-02-19','2028-02-28'),('2026-12-31','2027-03-21','2027-03-31')]
for base,reminder,due in examples:
 r=target(raw(policyFrom=base));check('explicit calendar '+base,(r['dueDate'],r['contractDueDate'])==(reminder,due),r)
 check('actual lead '+base,r['accountingLeadDays']==(date.fromisoformat(due)-date.fromisoformat(reminder)).days)
for year in (2026,2027,2028,2029,2030):
 for month in range(1,13):
  for day in (1,calendar.monthrange(year,month)[1]):
   base=date(year,month,day).isoformat();p=raw(policyFrom=base);before=copy.deepcopy(p);r=target(p)
   check('all months oracle '+base,r['dueDate']==oracle(year,month),r)
   check('original90 retained '+base,r['contractDueDate']==(date(year,month,calendar.monthrange(year,month)[1])+timedelta(days=90)).isoformat())
   check('read leaves source unchanged '+base,p==before)
   p['transactions']=build_premium_transactions(p)
   details=transaction_details(p,'2026-01-01T01:00:00Z')
   ri=next(d for d in details.values() if d.get('partyType')=='reinsurer' and d.get('allianzFacility'))
   check('cash ledger uses reminder and unchanged deadline '+base,(ri['dueDate'],ri['contractDueDate'])==(r['dueDate'],r['contractDueDate']))
for bad in ('','garbage','2026-02-30',None):check('missing/invalid dates stay blank '+str(bad),reminder_date(bad)=='')
p=raw(installmentEnabled=True,performanceInstallments=[{'id':'I1','paymentBaseDate':'2026-01-10','premium':500,'paymentTermsDays':90,'reinsurerPaymentTerms':{'r1':90}},{'id':'I2','paymentBaseDate':'2026-02-10','premium':500,'paymentTermsDays':90,'reinsurerPaymentTerms':{'r1':90}}])
check('each installment has its own reminder month',[(r['dueDate'],r['contractDueDate']) for r in items(p) if r.get('allianzFacility')]==[('2026-04-20','2026-05-01'),('2026-05-21','2026-05-29')])
for sign in (1,-1):
 for effective,announced,expected in [('2026-01-20','2026-02-02T17:00:00Z','2026-05-21'),('2026-03-01','2026-02-03T00:00:00Z','2026-06-20')]:
  p=raw(parentTwRef='ROOT',endoEffectiveDate=effective,endorsementAnnouncedAt=announced,originalPremium=200*sign);p['reinsurers'][0]['premium']=160*sign
  r=target(p);check('signed endorsement later Taiwan date '+str(sign)+effective,r['dueDate']==expected,r)
  p['endorsementAnnouncedAt']='';check('draft endorsement never invents reminder '+str(sign),target(p)['dueDate']=='')
p=raw();p['transactions']=build_premium_transactions(p)
def ri_detail(p,day):return next(d for d in transaction_details(p,day+'T01:00:00Z').values() if d.get('partyType')=='reinsurer' and d.get('allianzFacility'))
for day,status in [('2026-04-19','upcoming'),('2026-04-20','reminder'),('2026-04-30','reminder'),('2026-05-01','due_today'),('2026-05-02','overdue')]:
 d=ri_detail(p,day);check('reminder and overdue boundary '+day,d['paymentStatus']==status,d['paymentStatus'])
check('Sunday reminder not adjusted',date.fromisoformat(target(raw(policyFrom='2026-12-01'))['dueDate']).weekday()==6)
other_names=[NAME.replace(' (Facility)',''),'Allianz Other (Facility)',"Lloyd's Underwriter Syndicate No. 0609 AUW (Facility)",'Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)','Great American Insurance Company, Singapore Branch (Facility)','QBE Hongkong & Shanghai Insurance Limited, Hong Kong Branch (Facility)','Ordinary QA']
count=0
for klass in ('Property','Commercial General Liability','Marine'):
 for name in [NAME]+other_names:
  for month in (1,2,11,12):
   p=raw(classOfBusiness=klass,policyFrom=f'2026-{month:02d}-10');p['reinsurers'][0]['name']=name
   p['transactions']=build_premium_transactions(p)
   with patch('cases.allianz_accounting.payment_dates',old_dates):old=items(p);old_detail=transaction_details(p,'2026-01-01T01:00:00Z')
   new=items(p);new_detail=transaction_details(p,'2026-01-01T01:00:00Z')
   target_scope=klass=='Property' and name==NAME
   if not target_scope:
    check('non-target schedules and cash details identical '+klass+name+str(month),old==new and old_detail==new_detail);count+=1
   else:
    for a,b in zip(old,new):
     if b.get('allianzFacility'):
      a={k:v for k,v in a.items() if k not in ('dueDate','accountingLeadDays')};b={k:v for k,v in b.items() if k not in ('dueDate','accountingLeadDays')}
     check('only reminder metadata changes '+str(month)+a['partyType'],a==b)
p=raw();p['reinsurers'][0]['sharePct']=50;p['reinsurers'].append({'name':'Ordinary QA','sharePct':50,'premium':800,'riCommPct':0,'taxPct':0,'paymentTermsDays':90})
with patch('cases.allianz_accounting.payment_dates',old_dates):old=items(p)
new=items(p)
check('mixed case Cedant and ordinary rows unchanged',[r for r in old if not r.get('allianzFacility')]==[r for r in new if not r.get('allianzFacility')])
print('RESULT '+json.dumps({'passed':True,'checks':len(checks),'nonTargetComparisons':count,'labels':checks}))
