"""Exercise owner-approved business outcomes through API and production calculations."""
from pathlib import Path
exec(Path('/app/qa/suites/case_workflow.py').read_text().split('try:\n    with transaction.atomic():')[0])
from datetime import datetime, timezone as dtz
from django.utils import timezone
from masterdata.models import MasterRecord
from cases.draft import normalize_draft, validate_announce_ready, loss_record_save_errors
from cases.property_original import VERSION, VERSION_KEY, enabled, totals, allocate, periods, report_values, refresh_transactions, persist_settlements
from cases.cash_ledger import transaction_details
from cases.calc.payment_terms import build_payment_schedule
from cases.calc.signed_slip import reminder_due
from cases.calc.accounting import build_premium_transactions
from production.calc import build_production_preview
from production.closing import confirm_case
from production.views import case_source
from reminders.messages import contact_for
wf_ready=ready

def p_ready(**over):
    base=wf_ready(classOfBusiness='Property',classCode='PD',originalInsuredCn='測試保戶',
        reinsuredRetention="Advice of Reinsured's retention waived.",currency='TWD',originalPremium=1001,riCommPct=12.5,taxPct=1.5,
        situations=[dict(address='1 Test Road',postcode='SW1A 1AA')],
        reinsurers=[dict(name='Property RI A',sharePct=33.33,premium=800,riCommPct=10,taxPct=1,paymentTermsDays=90),dict(name='Property RI B',sharePct=33.33,premium=800,riCommPct=10,taxPct=1,paymentTermsDays=60)])
    base.setdefault('basisOfValuation', 'Replacement Value')
    base.update(over);return base

def new_case(client,**over):
    r=call(client,'post','/api/cases',{'case':p_ready(**over)})
    assert r.status_code==201,(r.status_code,r.content)
    return Case.objects.get(case_uid=r.json()['case']['caseUid'])

def documents(c):
    return [doc(c,'offer'),doc(c,'confirmation',[r['name'] for r in c.payload['reinsurers']])]

def posted(client,**over):
    c=new_case(client,**over);documents(c);r=announce(client,c)
    assert r.status_code==200,(r.status_code,r.content)
    c.refresh_from_db();return c

def update(client,c,changes,reason='Approved test change'):
    c.refresh_from_db();payload=copy.deepcopy(c.payload);payload.update(changes)
    r=call(client,'put','/api/cases',{'caseUid':str(c.case_uid),'rowVersion':c.row_version,'case':payload,'reason':reason,'reverseCorrectionConfirmed':True})
    c.refresh_from_db();return r

def tx_rows(c,leg):
    c.refresh_from_db();return [t for t in c.payload.get('transactions',[]) if t.get('legType')==leg and not t.get('reversed') and not t.get('isReversalEntry')]

def pay(client,c,leg,index=0,value=None):
    candidates=tx_rows(c,leg)
    if leg=='Leg 1' and value is None:
        periods=list(dict.fromkeys(t.get('installmentId') for t in candidates))
        group=[t for t in candidates if t.get('installmentId')==periods[index]]
    else:group=[candidates[index]]
    details=transaction_details(c.payload)
    allocations=[{'caseUid':str(c.case_uid),'rowVersion':c.row_version,'txNo':row['txNo'],
                  'amount':abs(details[row['txNo']]['outstanding']) if value is None else value} for row in group]
    response=call(client,'post','/api/accounting',{'action':'record_transaction_payments','paymentDate':'2026-10-22',
        'note':'QA synthetic registration','amount':sum(a['amount'] for a in allocations),'allocations':allocations})
    if response.status_code>=400 and value is None:print('PAY CHECK',leg,index,response.status_code,response.content[:1200],flush=True)
    return response

def preview(c,month=None,rate=30):
    c.refresh_from_db();month=month or timezone.localtime(c.announced_at).strftime('%Y-%m')
    return build_production_preview([case_source(c)],month,{month:{'USD':rate}},[])

with transaction.atomic():
 try:
    staff=person('sales','reinsurance',name='Property Executive',email='ae@property.test',is_split_eligible=True)
    owner=person('sales','reinsurance',name='Property Owner',email='owner@property.test',is_split_eligible=True)
    other=person('viewer','business_1',name='Property Other Staff',email='other@property.test',is_split_eligible=True)
    finance=person('accounting_manager','finance',name='Property Finance')
    sales=account(staff,'property-sales');fin=account(finance,'property-finance')
    option_rows=call(sales,'get','/api/personnel-options').json()['personnel']
    check('Case personnel options expose roles for required Split filtering',next(r for r in option_rows if r['id']==staff.pk)['roleCode']=='sales' and next(r for r in option_rows if r['id']==other.pk)['roleCode']=='viewer' and all('department' in r for r in option_rows))
    blank=dict(reinsuranceStructure='QS',classOfBusiness='Property',classCode='PD',installmentEnabled=True,performanceInstallments=[dict(id='I1')],splitEnabled=True,splitParties=[dict(pct=40),dict(pct=60)])
    r=call(sales,'post','/api/cases',{'case':blank})
    check('Draft may omit loss fields, people and incomplete installment',r.status_code==201,r.content[:500])
    incomplete=Case.objects.get(case_uid=r.json()['case']['caseUid']) if r.status_code==201 else None
    if incomplete:
        check('policy version is server-owned on a new Draft',incomplete.payload.get(VERSION_KEY)==VERSION)
        check('incomplete Draft cannot Announce',announce(sales,incomplete).status_code==400)
    p=p_ready(ownerPersonnelId=owner.pk,ae=staff.name)
    for postcode in ('SW1A 1AA','12345-6789','ABCDE1234567890','100'):
        check('international postcode accepted '+postcode,not normalize_draft({**p,'situations':[dict(address='Road',postcode=postcode)]})['errors'])
    check('invalid postcode characters rejected',bool(normalize_draft({**p,'situations':[dict(address='Road',postcode='12@34')]})['errors']))
    check('equal effective and expiry dates rejected',bool(normalize_draft({**p,'policyTo':p['policyFrom']})['errors']))
    for field in ('originalInsuredCn','reinsuredRetention','riCommPct','taxPct','paymentTermsDays'):
        q=normalize_draft({**p,field:None})['value'];issues=validate_announce_ready(q,allow_zero_loss_years=True)
        check('Review / Announce requires '+field,any(i['field']==field for i in issues),issues)
    check('Original Case Premium must be positive',any(i['field']=='originalPremium' for i in validate_announce_ready(normalize_draft({**p,'originalPremium':0})['value'],allow_zero_loss_years=True)))
    check('aggregate limit zero is rejected at Review',any(i['field']=='aggregateLimit' for i in validate_announce_ready(normalize_draft({**p,'aggregateLimit':0})['value'],allow_zero_loss_years=True)))
    check('total Order Hereon above100 rejected',any(i['field']=='reinsurers' for i in validate_announce_ready(normalize_draft({**p,'reinsurers':[{**p['reinsurers'][0],'sharePct':100},{**p['reinsurers'][1],'sharePct':1}]})['value'],allow_zero_loss_years=True)))
    check('total Order Hereon below100 accepted',not validate_announce_ready(normalize_draft(p)['value'],allow_zero_loss_years=True),validate_announce_ready(normalize_draft(p)['value'],allow_zero_loss_years=True))
    check('USD precision rejects three decimal places',bool(normalize_draft({**p,'currency':'USD','originalPremium':1000.001})['errors']))
    zero=normalize_draft({**p,'lossRecordYears':0,'lossAdvisedDate':'2026-01-01'})['value']
    check('New Year0 is valid with no loss entries',not loss_record_save_errors(zero) and not validate_announce_ready(zero,allow_zero_loss_years=True))
    check('Renew Year0 rejected',bool(loss_record_save_errors({**zero,'newOrRenew':'Renew'})))
    split=[dict(personnelId=staff.pk,name=staff.name,pct=40),dict(personnelId=other.pk,name=other.name,pct=60)]
    wrong=call(sales,'post','/api/cases',{'case':{**p,'splitEnabled':True,'splitParties':[{**split[1],'pct':40},{**split[0],'pct':60}]}})
    check('Split staff roles cannot be swapped through API',wrong.status_code==400,wrong.content)
    c=posted(sales,ownerPersonnelId=owner.pk,ae=staff.name)
    check('Announce creates independent T1/T2/T3 per reinsurer',len(c.payload['transactions'])==6 and all(len(tx_rows(c,leg))==2 for leg in ('Leg 1','Leg 2','Leg 3')))
    t=totals(c.payload)
    check('CaseT1 sums Order Hereon before each calculation step',t['cedantPremium']==667 and t['cedantCommission']==83 and t['cedantTax']==10 and t['leg1']==574,t)
    check('T2 is independent and CaseT3 is T1 minus allT2',t['t2s']==[237,237] and t['leg3']==100,t)
    check('tail assigned by descending positive share',allocate(5,[0,10,30,60],c.payload)==[0,1,2,2])
    precision={**c.payload,'currency':'USD','originalPremium':982598.59,'riCommPct':5,'taxPct':1,
        'reinsurers':[dict(name='A',sharePct=12.5,premium=23863.19,riCommPct=10,taxPct=1),dict(name='B',sharePct=25,premium=815736.35,riCommPct=12.5,taxPct=1),dict(name='C',sharePct=37.5,premium=579316.44,riCommPct=17.35,taxPct=1)]}
    from cases.calc.accounting import calc_legs_for_reinsurer
    check('half-cent T2 schedule and ledger use exact decimal rounding',totals(precision)['t2s']==[2654.78,176402.99,177379.45] and [calc_legs_for_reinsurer(precision,r)['leg2'] for r in precision['reinsurers']]==[2654.78,176402.99,177379.45])
    version=c.row_version
    check('T2 payment requires full T1 receipt and settlement',pay(fin,c,'Leg 2').status_code>=400)
    check('partial premium receipt rejected',pay(fin,c,'Leg 1',value=1).status_code==400)
    check('full T1 receipt is accepted before Production',pay(fin,c,'Leg 1').status_code==200)
    c.refresh_from_db();first=tx_rows(c,'Leg 1')[0];d=transaction_details(c.payload)[first['txNo']]
    check('full T1 cash atomically settles and locks T1',first['settlement']=='settled' and d['settlement']=='settled' and not d['canCancelSettlement'] and d['amountEditLocked'])
    check('one bank receipt has two separate T1 allocations',len(c.payload['paymentEntries'])==2 and len({e['batchId'] for e in c.payload['paymentEntries']})==1)
    check('settled T1 blocks Case Premium changes',update(sales,c,{'originalPremium':2000}).status_code==409)
    check('settled T1 locks its Payment Terms',update(sales,c,{'paymentTermsDays':31}).status_code==409)
    check('settled T1 locks shared Payment Base Date',update(sales,c,{'policyFrom':'2026-03-02'}).status_code==409)
    ris=copy.deepcopy(c.payload['reinsurers']);ris[0]['premium']=810
    r=update(sales,c,{'reinsurers':ris})
    check('after T1 settlement unrecorded T2/T3 can change',r.status_code==200,r.content[:600])
    check('settled T1 amount unchanged after permitted T2 edit',sum(row['amount'] for row in tx_rows(c,'Leg 1'))==574)
    check('financial edits require a reason',update(sales,c,{'remark':'Test'},reason='').status_code==409)
    check('financial edit before/after history is retained',bool(c.payload.get('propertyEditHistory')) and c.payload['propertyEditHistory'][-1]['amountsBefore']['leg2']!=c.payload['propertyEditHistory'][-1]['amountsAfter']['leg2'])
    check('full T2 payment accepted and auto settled',pay(fin,c,'Leg 2',0).status_code==200)
    check('individual T2 locks immediately',tx_rows(c,'Leg 2')[0]['settlement']=='settled')
    ris=copy.deepcopy(c.payload['reinsurers']);ris[0]['premium']=820
    check('settled T2 amount cannot change',update(sales,c,{'reinsurers':ris}).status_code==409)
    ris=copy.deepcopy(c.payload['reinsurers']);ris[1]['premium']=820
    check('first settled T3 locks peer T2 amount',update(sales,c,{'reinsurers':ris}).status_code==409)
    check('last T2 full payment accepted',pay(fin,c,'Leg 2',1).status_code==200)
    check('T3 auto settles after T1 and everyT2',tx_rows(c,'Leg 3')[0]['settlement']=='settled')
    check('T3 settlement creates no bank record',len(c.payload['paymentEntries'])==4 and not any('T3' in e.get('transactionNo','') for e in c.payload['paymentEntries']))
    check('group no longer permits Split changes',update(sales,c,{'splitEnabled':True,'splitParties':split}).status_code==409)
    # Document-description fields remain editable despite complete financial settlement.
    check('document descriptions remain editable after settlement',update(sales,c,{'occupation':'Updated office wording'}).status_code==200)
    selected=CaseDocument.objects.filter(case=c,is_selected=True).first()
    r=call(sales,'put','/api/case-documents',{'caseUid':str(c.case_uid),'fileId':str(selected.pk),'selected':False})
    check('Announced selected attachments cannot be deselected',r.status_code==409)
    # Zero transactions settle without creating fake receipts.
    zero_payload=p_ready(ownerPersonnelId=owner.pk,ae=staff.name,reinsurers=[dict(name='Zero RI',sharePct=0,premium=800,riCommPct=10,taxPct=1,paymentTermsDays=90)])
    rejected=call(sales,'post','/api/cases',{'case':zero_payload})
    check('new zero-share case is rejected',rejected.status_code==400)
    # Historical zero-share rows remain readable/announcable without rewriting their shares.
    historic=normalize_draft(zero_payload,existing_premiums=zero_payload)['value']
    historic.pop('placingRulesVersion',None)
    historic['transactions']=build_premium_transactions(historic)
    historic['paymentEntries']=[]
    z=Case.objects.create(payload=historic,status='posted',created_by='qa',updated_by='qa')
    check('unchanged historical zero share remains valid',not normalize_draft(historic,existing_premiums=historic)['errors'])
    check('zero-share reinsurer creates no transactions or cash',not z.payload['transactions'] and not z.payload['paymentEntries'])
    # Split report rows conserve the Case totals and Other Staff is calculated first.
    s=posted(sales,ownerPersonnelId=owner.pk,ae=staff.name,splitEnabled=True,splitParties=split)
    rows_=preview(s)['rows']
    check('two report people per RI when Split enabled',len(rows_)==4)
    check('report premium conserves Case ceded premium',sum(r['premium'] for r in rows_)==667,rows_)
    check('report T3 conserves Case income',sum(r['income'] for r in rows_)==100)
    check('Other Staff gets60% of both premium and income',sum(r['premium'] for r in rows_ if r['ae']==other.name)==400 and sum(r['income'] for r in rows_ if r['ae']==other.name)==60,rows_)
    check('no Split report credits Account Executive',all(r['ae']==staff.name for r in preview(c)['rows']))
    # Partial Production: only unconfirmed RI can change, without changing confirmed rows.
    partial=posted(sales,ownerPersonnelId=owner.pk,ae=staff.name)
    original=preview(partial)['rows'];month=original[0]['month'];ri1=[r for r in original if r['reinsurer']=='Property RI A']
    state=confirm_case(case_source(partial),ri1,posting_month=month)
    partial.payload=state['payload'];partial.status=state['nextStatus'];partial.save()
    check('partial RI confirmation leaves Case posted',partial.status=='posted' and len(partial.payload['confirmedProductionKeys'])==1)
    ris=copy.deepcopy(partial.payload['reinsurers']);ris[1]['premium']=810
    r=update(sales,partial,{'reinsurers':ris})
    check('unconfirmed RI edit allowed with unchanged confirmed RI report',r.status_code==200,r.content[:600])
    check('Case Premium cannot change recognized RI report',update(sales,partial,{'originalPremium':2000}).status_code==409)
    check('AE locked after any RI Production confirmation',update(sales,partial,{'ae':owner.name}).status_code==409)
    check('Split locked after any RI Production confirmation',update(sales,partial,{'splitEnabled':True,'splitParties':split}).status_code==409)
    # Reverse only recognized RI performance, retain immutable original history.
    r=wf(sales,'reverse_case',partial);check('partial Production Case may Reverse while no Settlement',r.status_code==200,r.content[:600]);partial.refresh_from_db()
    negative=preview(partial)['rows']
    check('Reverse report has only previously recognized RI',len(negative)==len(ri1) and all(r['reinsurer']=='Property RI A' and r['isProductionReversal'] for r in negative),negative)
    check('Reverse uses exact negative original premium and income',sum(r['premium'] for r in negative)==-sum(r['premium'] for r in ri1) and sum(r['income'] for r in negative)==-sum(r['income'] for r in ri1))
    check('original positive Production snapshots retained',len(partial.payload['productionHistory'])==1 and all(abs(partial.payload['productionHistory'][0]['row'][k]-v)<1e-12 if isinstance(v,float) else partial.payload['productionHistory'][0]['row'][k]==v for k,v in ri1[0].items()))
    ref=partial.tw_ref
    r=update(sales,partial,{'occupation':'Corrected wording'})
    check('correction returns to Draft retaining same Ref',r.status_code==200 and partial.status=='draft' and partial.tw_ref==ref,r.content[:600])
    r=announce(sales,partial);partial.refresh_from_db()
    check('corrected Case repeats Announce using same immutable Ref',r.status_code==200 and partial.tw_ref==ref and partial.status=='posted',r.content[:600])
    check('re-Announce creates new ledger cycle once',len([t for t in partial.payload['transactions'] if not t.get('reversed') and not t.get('isReversalEntry')])==6)
    # Reverse before Production deletes active premium ledgers and records the event only.
    b=posted(sales,ownerPersonnelId=owner.pk,ae=staff.name)
    r=wf(sales,'reverse_case',b);b.refresh_from_db()
    check('pre-Production Reverse removes premium ledger rows',r.status_code==200 and not b.payload['transactions'] and bool(b.payload.get('propertyReversalHistory')),r.content[:400])
    # MDM title changes are effective immediately on open without rewriting stored Case.
    m=MasterRecord.objects.create(entity_type='clause',code='LMA3333',name='Latest revised MDM Title',created_by='test',updated_by='test')
    stored_title=s.payload['clauseDetails'][0]['title']
    loaded=call(sales,'get','/api/cases?caseUid='+str(s.case_uid)).json()['case']['payload']
    check('Case reads latest MDM Title verbatim',next(r['title'] for r in loaded['clauseDetails'] if r['code']=='LMA3333')=='Latest revised MDM Title')
    s.refresh_from_db();check('MDM title read does not rewrite stored Case',s.payload['clauseDetails'][0]['title']==stored_title)
    # Signed Slip: day30 and AE + Case Owner, no supervisor dependency.
    slip={**s.payload,'status':'posted','policyFrom':'2026-01-01'}
    check('Signed Slip first reminder on Effective+30',reminder_due(slip,[],'','2026-01-31') is not None and reminder_due(slip,[],'','2026-01-30') is None)
    check('Signed Slip reminder repeats every7days',reminder_due(slip,[],'2026-01-31','2026-02-06') is None and reminder_due(slip,[],'2026-01-31','2026-02-07') is not None)
    contact=contact_for(slip,[{'id':staff.pk,'name':staff.name,'email':staff.email},{'id':owner.pk,'name':owner.name,'email':owner.email}])
    check('Signed Slip recipients are AE and Case Owner',contact.get('aeEmail')==staff.email and contact.get('supervisorEmail')==owner.email,contact)
    # Facility / legacy accounting keeps its original algorithm and manual Settlement.
    legacy={**p,VERSION_KEY:'historical','twRef':'LEGACY'}
    check('historical precision retains current protections and aggregate historical layout',enabled(legacy) and len(build_premium_transactions(legacy))==4)
    facility={**p,VERSION_KEY:VERSION,'reinsurers':[{**p['reinsurers'][0],'name':'Test Re (Facility)'}]}
    check('Facility rules override the new ordinary accounting policy',not enabled(facility))
    # Exercise actual Generate / Close API and verify it does not generate a second ledger.
    final=posted(sales,ownerPersonnelId=owner.pk,ae=staff.name)
    Case.objects.exclude(pk=final.pk).update(is_archived=True,archived_at=timezone.now(),archived_by='test')
    source=call(fin,'get','/api/production-report?month='+month)
    check('Production preview API succeeds',source.status_code==200,source.content[:500])
    state=source.json();signature=state.get('sourceSignature') or state.get('preview',{}).get('sourceSignature')
    generated=call(fin,'post','/api/production-report',{'action':'generate','month':month,'sourceSignature':signature})
    check('Production Generate API succeeds',generated.status_code in (200,201),generated.content[:500])
    if generated.status_code in (200,201):
        report=generated.json()['report'];before=copy.deepcopy(final.payload['transactions'])
        closed=call(fin,'post','/api/production-report',{'action':'close','month':month,'reportUid':report['reportUid'],'rowVersion':report['rowVersion'],'sourceSignature':signature})
        final.refresh_from_db()
        check('Production Close confirms Case',closed.status_code==200 and final.status=='closed',closed.content[:700])
        check('Production Close does not duplicate Announce ledger',[(t['txNo'],t['amount']) for t in final.payload['transactions']]==[(t['txNo'],t['amount']) for t in before])
        check('confirmed Case description edits remain available',update(sales,final,{'constructionSelections':['A2 Class','C Class']}).status_code==200)
        check('confirmed Case financial edits cannot change recognized amounts',update(sales,final,{'originalPremium':2000}).status_code==409)
 finally:
    transaction.set_rollback(True)
for label,ok,detail in results:
    print(('PASS ' if ok else 'FAIL ')+label+(' '+str(detail)[:700] if not ok else ''))
passed=sum(ok for _,ok,_ in results)
print(f'{passed}/{len(results)} Property Original checks passed')
assert passed==len(results),[r for r in results if not r[1]]
