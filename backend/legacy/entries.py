"""Owner-approved new endorsements/claims. Historical rows are never edited.

2026-11-12 owner decisions (claims Q1–Q13, endorsements E1–E14, follow-ups):
- Sources: a claim only from an original premium row; an endorsement from a premium row or an endorsement.
- Locked to the source: Cedant, Settlement Party, Old Reference; claims also Insured (latest) and,
  for Property, currency; endorsements also currency, Share and the AE/Sub AE split.
- Payment rule is detected from the settlement party; ordinary-rule days stay editable.
- "Same policy" = same Old Reference; latest period = earliest start + latest expiry.
- Endorsements: effective date inside the latest period and not before the previous endorsement;
  Expiry may change (start fixed, at most 18 months); Endorsement No. unique per Old Reference;
  premium or brokerage must be non-zero; Revenue Month is automatic.
- Claims: Loss No. required, Cause of Loss optional, DOL inside the latest period.
- TWD amounts are whole numbers, others at most two decimals; never rounded silently.
"""
import copy
from datetime import date
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import LegacyTransaction, NumberCounter, LegacyReason
from .services import audit, state, fail
from .money import calculate, split_performance
from . import policy

BUSINESS={'sales','general_manager','admin'}
FIELDS={'reference','currency','revenueMonth','kind','insured','insuredCn','cedant','party','statementNo',
    'reinsurerRef','effectiveDate','expiryDate','lossDate','lossNo','causeOfLoss','claimNote','gross','share',
    'commissionRate','taxRate','brokerage','claim','claimReason','brokerageNote','ae','subAe','aePct','rule',
    'cedantDays','reinsurerDays','endorsementNo','installmentNo','newRenew','remark','oldReason','oldReasonText'}
# R/I Commission % and Tax % are pre-filled from the source (editable); Installment No. is shown and editable.
EMPTY_ON_COPY={'revenueMonth','gross','brokerage','claim','claimReason','lossDate','lossNo','causeOfLoss',
    'claimNote','brokerageNote','endorsementNo','oldReason','oldReasonText','remark'}
SOURCES={'claim':('premium',),'endorsement':('premium','endorsement')}
LABELS={'reference':'Old Reference','cedant':'Cedant','party':'Settlement Party','currency':'Currency','insured':'Insured (English)',
    'insuredCn':'Insured (Chinese)','share':'Share (%)','subAe':'Sub AE','aePct':'AE / Sub AE split','rule':'Payment rule',
    'revenueMonth':'Revenue Month','effectiveDate':'Effective Date','expiryDate':'Expiry Date','cedantDays':'Cedant terms',
    'reinsurerDays':'Reinsurer terms','kind':'Transaction type','gross':'100% Premium','commissionRate':'R/I Commission (%)',
    'taxRate':'Tax (%)','brokerage':'Brokerage','newRenew':'New / Renew'}


def locked_fields(data):
    kind=data.get('kind')
    common={'kind','reference','cedant','party','rule','revenueMonth','newRenew'}
    if kind=='claim':
        keys=common|{'insured','insuredCn','effectiveDate','expiryDate','share','gross','commissionRate','taxRate',
                     'brokerage','subAe','aePct','cedantDays','reinsurerDays'}
        if str(data.get('classOfBusiness') or 'Property')=='Property':keys|={'currency'}
        return keys
    keys=common|{'currency','share','subAe','aePct'}
    if data.get('rule')!='ordinary':keys|={'cedantDays','reinsurerDays'}
    return keys


def business(person):
    if person.role_code not in BUSINESS:fail('Business access is required.',403)


def dates(value,label):
    try:return date.fromisoformat(value)
    except (ValueError,TypeError):fail(label+' must be a valid date.')


def create(person,body):
    business(person)
    kind=body.get('kind')
    if kind not in ('endorsement','claim'):fail('Select Endorsement or Claim.')
    try:source=LegacyTransaction.objects.select_for_update().get(pk=body.get('referenceTransaction'),status='confirmed')
    except (LegacyTransaction.DoesNotExist,ValueError,ValidationError):fail('Select a confirmed source transaction.')
    if (source.data or {}).get('kind','premium') not in SOURCES[kind]:
        fail('Claims can be added only to an original premium transaction.' if kind=='claim'
             else 'Endorsements can be added only to a premium or endorsement transaction.')
    data={k:copy.deepcopy(v) for k,v in source.data.items() if k in FIELDS-EMPTY_ON_COPY}
    start,end=policy.latest_period(source.reference)
    data.update(kind=kind,currency=source.currency,revenueMonth='',
        expiryDate=end.isoformat() if end else source.data.get('expiryDate',''),
        sourceEffectiveDate=start.isoformat() if start else source.data.get('effectiveDate',''),
        sourceExpiryDate=end.isoformat() if end else source.data.get('expiryDate',''),
        sourceAe=source.data.get('ae',''),sourceSubAe=source.data.get('subAe',''),sourceReference=source.reference,
        rule=policy.detected_rule(source.data.get('party','')))
    for key in ('classOfBusiness','classCode'):
        if source.data.get(key):data[key]=source.data[key]
    if not data.get('subAe'):data['aePct']=100
    elif data.get('aePct') not in (40,70):data['aePct']=source.data.get('aePct')
    if kind=='claim':
        data['insured'],data['insuredCn']=policy.latest_insured(source)
        data.update(effectiveDate=data['sourceEffectiveDate'],gross=0,commissionRate=0,taxRate=0,brokerage=0,subAe='',aePct=100)
    if data['rule']!='ordinary':data['cedantDays']=90
    t=LegacyTransaction.objects.create(reference=source.reference,currency=source.currency,
        owner_id=person.pk,created_by_id=person.pk,reference_transaction=source,data=data)
    audit(person,t.pk,'draft_created',after=state(t))
    return t


def ready(t,stamp):
    from personnel.models import Personnel
    from .ledger import RULE_NAMES
    d=t.data;kind=d.get('kind')
    if kind not in ('endorsement','claim'):fail('Select Endorsement or Claim.')
    source=t.reference_transaction
    if source is None or source.status!='confirmed' or (source.data or {}).get('kind','premium') not in SOURCES[kind]:
        fail('The source transaction is no longer available for this transaction type.')
    for key,label in [('reference','Old reference'),('insured','Insured'),('cedant','Cedant'),('party','Settlement party'),('ae','AE')]:
        if not isinstance(d.get(key),str) or not d[key].strip():fail(label+' is required.')
        if len(d[key])>(192 if key=='reference' else 240):fail(label+' exceeds the supported length.')
    if t.currency not in ('TWD','USD','MYR','EUR','JPY','GBP','HKD'):fail('Select a supported currency.')
    start=dates(d.get('effectiveDate'),'Effective Date');end=dates(d.get('expiryDate'),'Expiry Date')
    if start>end:fail('Effective Date must not be later than Expiry Date.')
    if not Personnel.objects.filter(name=d.get('ae'),is_active=True).exists():fail('Select an employed AE.')
    if d.get('subAe'):
        # A Sub AE carried over from the source is kept even if no longer employed (native rule).
        if d.get('subAe')!=d.get('sourceSubAe') and not Personnel.objects.filter(name=d['subAe'],is_active=True).exists():
            fail('Select an employed Sub AE.')
        if d.get('ae')==d.get('subAe'):fail('AE and Sub AE must be different people.')
    d['rule']=policy.detected_rule(d.get('party',''))
    if d['rule'] not in RULE_NAMES:fail('The payment rule could not be determined.')
    if d['rule']!='ordinary':d['cedantDays']=90
    for key in ('cedantDays','reinsurerDays'):
        if type(d.get(key)) is not int or d[key]<15:fail('Payment terms must be whole calendar days of at least 15.')
    lo,hi=policy.latest_period(t.reference,exclude=t.pk)
    if kind=='claim':
        loss=str(d.get('lossNo') or '').strip()
        if not loss:fail('Loss No. is required.')
        if len(loss)>160 or len(str(d.get('causeOfLoss') or ''))>2000:fail('Loss No. or Cause of Loss exceeds the supported length.')
        d['lossNo']=loss
        error=policy.money_error(d.get('claim'),'Claim amount',t.currency)
        if error:fail(error)
        dol=dates(d.get('lossDate'),'DOL')
        if not lo or not hi or not lo<=dol<=hi:fail('DOL must fall within the policy period of this Old Reference.')
        if d.get('revenueMonth'):fail('Claims must not have a Revenue Month.')
    else:
        no=str(d.get('endorsementNo') or '').strip()
        if not no:fail('Endorsement No. is required.')
        norm=' '.join(no.split()).casefold()
        if any(' '.join(str((x or {}).get('endorsementNo') or '').split()).casefold()==norm for x in
               LegacyTransaction.objects.filter(reference=t.reference,data__kind='endorsement',status='confirmed').exclude(pk=t.pk)
               .values_list('data',flat=True)):
            fail('This Endorsement No. already exists for this Old Reference.')
        if lo and hi and not lo<=start<=hi:fail('The endorsement Effective Date must fall within the policy period.')
        previous=policy.previous_endorsement_date(t.reference,exclude=t.pk)
        if previous and start<previous:fail('The endorsement Effective Date must not be earlier than the previous endorsement.')
        if lo:
            from cases.endorsement_rules import add_months
            try:limit=add_months(lo,18)
            except ValueError:limit=date.max
            if end>limit:fail('The complete insurance period must not exceed 18 calendar months.')
        for key,label in (('gross','100% Premium'),('brokerage','Brokerage amount')):
            error=policy.money_error(d.get(key),label,t.currency)
            if error:fail(error)
        try:
            if float(d.get('gross') or 0)==0 and float(d.get('brokerage') or 0)==0:
                fail('Enter a 100% Premium or a Brokerage amount; an endorsement cannot be zero.')
        except (TypeError,ValueError):fail('Enter valid amounts.')
        month=policy.revenue_month(d.get('effectiveDate'),stamp)
        d['revenueMonth']=month;t.revenue_month=month
        try:limit=end.replace(year=end.year+5)
        except ValueError:limit=end.replace(year=end.year+5,day=28)
        if timezone.localtime(stamp).date()>limit:
            if not LegacyReason.objects.filter(code=d.get('oldReason'),active=True).exists():fail('Select a reason for an endorsement over five years after expiry.')
            if d.get('oldReason')=='other' and not str(d.get('oldReasonText') or '').strip():fail('Explain the reason for Other.')
    try:
        amounts=calculate(d)
        if kind=='endorsement':split_performance(d,amounts,1)
    except ValueError as exc:fail(str(exc))
    return amounts


def change(person,body):
    business(person)
    try:t=LegacyTransaction.objects.select_for_update().select_related('reference_transaction').get(pk=body.get('id'))
    except (LegacyTransaction.DoesNotExist,ValueError,ValidationError):fail('Transaction not found.',404)
    if body.get('action')=='transfer':
        return transfer(person,t,body)
    if body.get('action')=='retract':
        return retract(person,t,body)
    if t.historical or t.status!='draft' or t.owner_id!=person.pk:fail('Only the draft owner can edit or confirm this transaction.',403)
    if type(body.get('version')) is not int or body['version']!=t.version:fail('This transaction changed. Refresh before continuing.',409,'version_conflict')
    action=body.get('action');before=state(t)
    if action=='save':
        data=body.get('data')
        if not isinstance(data,dict) or set(data)-FIELDS:fail('The draft contains unsupported fields.')
        if any(isinstance(value,(dict,list)) for value in data.values()):fail('Draft fields must be scalar values.')
        locked=locked_fields(t.data)
        for key in sorted(set(data)&locked):
            if data[key]!=t.data.get(key) and not (data[key] in (None,'') and t.data.get(key) in (None,'')):
                fail(LABELS.get(key,key)+' follows the source transaction and cannot be changed.')
        t.data.update({k:copy.deepcopy(v) for k,v in data.items() if k not in locked})
        if t.data.get('kind')=='claim' and str(t.data.get('classOfBusiness') or 'Property')!='Property':
            currency=str(t.data.get('currency') or '').strip().upper()
            if currency not in ('TWD','USD','MYR','EUR','JPY','GBP','HKD'):fail('Select a supported currency.')
            t.currency=currency;t.data['currency']=currency
    elif action=='confirm':
        stamp=timezone.now();t.data['amounts']=ready(t,stamp)
        if not t.number:
            year=timezone.localtime(stamp).year
            NumberCounter.objects.get_or_create(year=year)
            counter=NumberCounter.objects.select_for_update().get(pk=year)
            counter.value+=1;counter.save(update_fields=['value'])
            t.number=f'LTX-{year}-{counter.value:06d}'
        t.status='confirmed'
        if not t.first_confirmed_at:t.first_confirmed_at=stamp
        t.data['confirmedAt']=stamp.isoformat()
        actor={'id':f'personnel:{person.pk}','name':person.name}
        master=policy.link_insured(t.data.get('insuredCn'),actor,str(t.uid))
        if master:t.data['insuredMasterId']=master
        # Zero cash legs settle automatically, including a zero Swiss Cedant leg.
        # No review identity or bank receipt is fabricated.
        from .ledger import payload_for
        from cases.property_original import persist_settlements
        payload=payload_for(t)
        try:persist_settlements(payload,stamp.isoformat(),actor)
        except (ValueError,OverflowError):fail('The selected payment terms exceed the supported calendar range.')
        t.financial={key:copy.deepcopy(payload.get(key,{} if key=='swissAccounting' else []))
                     for key in ('paymentEntries','financeClaimTracking','swissAccounting','transactions')}

    else:fail('Unsupported transaction action.')
    t.version+=1;t.save()
    audit(person,t.pk,'draft_saved' if action=='save' else 'transaction_confirmed',before,state(t),str(t.data.get('claimReason') or ''))
    return t


def can_retract(person,t):
    if t.historical or t.batch_id or t.status!='confirmed' or t.owner_id!=person.pk or person.role_code not in BUSINESS:return False
    if t.financial.get('paymentEntries'):return False
    from cases.finance_workflow import active_reviews
    if any(uid==str(t.uid) for uid,no in active_reviews({str(t.uid)})):return False
    from production.models import ProductionReport
    return not any(any(row.get('legacyTransactionId')==str(t.uid) for row in report.rows)
                   for report in ProductionReport.objects.filter(status='closed').only('rows'))


def retract(person,t,body):
    if not can_retract(person,t):fail('Only the owner can retract a transaction without active reconciliation, receipt/payment history or closed Production.',409)
    if type(body.get('version')) is not int or body['version']!=t.version:fail('Refresh this transaction before continuing.',409,'version_conflict')
    before=state(t);t.status='draft';t.version+=1;t.save()
    audit(person,t.pk,'transaction_retracted',before,state(t))
    return t


def can_transfer(person,t):
    if person.role_code!='admin' or t.historical or t.status!='draft':return False
    from personnel.models import Personnel
    return not Personnel.objects.filter(pk=t.owner_id,is_active=True,account_status='active',role_code__in=BUSINESS).exists()


def transfer(person,t,body):
    if not can_transfer(person,t):fail('Only administrators may transfer drafts whose owner is no longer eligible.',403)
    if type(body.get('version')) is not int or body['version']!=t.version:fail('Refresh this draft before continuing.',409,'version_conflict')
    reason=body.get('reason')
    if not isinstance(reason,str) or not reason.strip():fail('A transfer reason is required.')
    from personnel.models import Personnel
    from django.contrib.auth import get_user_model
    if type(body.get('ownerId')) is not int or body['ownerId']<=0:fail('Select a valid new owner.')
    target=Personnel.objects.filter(pk=body.get('ownerId'),is_active=True,account_status='active',role_code__in=BUSINESS).first()
    if not target or not target.auth_user_id or not get_user_model().objects.filter(pk=target.auth_user_id,is_active=True).exists():fail('Select an employed business user with an enabled account.')
    before=state(t);t.owner_id=target.pk;t.version+=1;t.save()
    audit(person,t.pk,'draft_transferred',before,state(t),reason.strip())
    return t
