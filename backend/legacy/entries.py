"""Owner-approved new endorsements/claims. Historical rows are never edited."""
import copy
from datetime import date
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import LegacyTransaction, NumberCounter, LegacyReason
from .services import audit, state, fail
from .money import calculate, split_performance

BUSINESS={'sales','general_manager','admin'}
FIELDS={'reference','currency','revenueMonth','kind','insured','insuredCn','cedant','party','statementNo',
    'reinsurerRef','effectiveDate','lossDate','claimNote','gross','share','commissionRate','taxRate','brokerage',
    'claim','claimReason','brokerageNote','ae','subAe','aePct','rule','cedantDays','reinsurerDays',
    'endorsementNo','installmentNo','newRenew','remark','oldReason','oldReasonText'}
EMPTY_ON_COPY={'revenueMonth','gross','commissionRate','taxRate','brokerage','claim','claimReason','lossDate',
    'claimNote','brokerageNote','endorsementNo','oldReason','oldReasonText','remark'}


def business(person):
    if person.role_code not in BUSINESS:fail('Business access is required.',403)


def dates(value,label):
    try:return date.fromisoformat(value)
    except (ValueError,TypeError):fail(label+' must be a valid date.')


def create(person,body):
    business(person)
    if body.get('kind') not in ('endorsement','claim'):fail('Select Endorsement or Claim.')
    try:source=LegacyTransaction.objects.select_for_update().get(pk=body.get('referenceTransaction'),status='confirmed')
    except (LegacyTransaction.DoesNotExist,ValueError,ValidationError):fail('Select a confirmed source transaction.')
    data={k:copy.deepcopy(v) for k,v in source.data.items() if k in FIELDS-EMPTY_ON_COPY}
    data.update(kind=body['kind'],currency=source.currency,revenueMonth='',expiryDate=source.data.get('expiryDate',''),
        sourceEffectiveDate=source.data.get('effectiveDate',''),sourceExpiryDate=source.data.get('expiryDate',''),
        sourceAe=source.data.get('ae',''),sourceReference=source.reference)
    if body['kind']=='claim':data.update(gross=0,commissionRate=0,taxRate=0,brokerage=0,subAe='',aePct=100)
    t=LegacyTransaction.objects.create(reference=source.reference,currency=source.currency,
        owner_id=person.pk,created_by_id=person.pk,reference_transaction=source,data=data)
    audit(person,t.pk,'draft_created',after=state(t))
    return t


def ready(t,stamp):
    from personnel.models import Personnel
    from production.models import ProductionReport
    from .ledger import RULE_NAMES,detect_rule
    import re
    d=t.data;kind=d.get('kind')
    if kind not in ('endorsement','claim'):fail('Select Endorsement or Claim.')
    for key,label in [('reference','Old reference'),('insured','Insured'),('cedant','Cedant'),('party','Settlement party'),('ae','AE')]:
        if not isinstance(d.get(key),str) or not d[key].strip():fail(label+' is required.')
        if len(d[key])>(192 if key=='reference' else 240):fail(label+' exceeds the supported length.')
    if t.currency not in ('TWD','USD','MYR','EUR','JPY','GBP','HKD'):fail('Select a supported currency.')
    start=dates(d.get('effectiveDate'),'Effective Date');end=dates(d.get('expiryDate'),'Expiry Date')
    if start>end:fail('Effective Date must not be later than Expiry Date.')
    for name in filter(None,[d.get('ae'),d.get('subAe')]):
        if not Personnel.objects.filter(name=name,is_active=True).exists():fail('Select employed AE / Sub AE personnel.')
    if d.get('ae')==d.get('subAe'):fail('AE and Sub AE must be different people.')
    if d.get('rule') not in RULE_NAMES:fail('Select a payment rule before confirmation.')
    detected=detect_rule(d['party'])
    if detected and detected!='ordinary' and detected!=d.get('rule'):fail('The payment rule must match the selected MDM settlement party.')
    if kind=='endorsement' and d['rule']!='ordinary' and d.get('cedantDays')!=90:fail('Facility Cedant terms are fixed at 90 calendar days.')
    for key in ('cedantDays','reinsurerDays'):
        if type(d.get(key)) is not int or d[key]<15:fail('Payment terms must be whole calendar days of at least 15.')
    if kind=='claim':
        dol=dates(d.get('lossDate'),'DOL')
        lo=dates(d.get('sourceEffectiveDate'),'Source Effective Date')
        hi=dates(d.get('sourceExpiryDate'),'Source Expiry Date')
        if not lo<=dol<=hi:fail('DOL must fall within the selected source transaction period.')
        if d.get('revenueMonth'):fail('Claims must not have a Revenue Month.')
    else:
        if not str(d.get('endorsementNo') or '').strip():fail('Endorsement No. is required.')
        month=d.get('revenueMonth','')
        if not isinstance(month,str) or not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',month):fail('Select a Revenue Month.')
        if ProductionReport.objects.filter(year_month=month,status='closed').exists():fail('Select an unclosed Revenue Month.',409)
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
        if data.get('kind',t.data['kind'])!=t.data['kind']:fail('The transaction type cannot be changed.')
        if t.data['kind']=='claim' and 'effectiveDate' in data and data['effectiveDate']!=t.data.get('sourceEffectiveDate'):
            fail('A claim retains the selected source Effective Date.')
        t.data.update(copy.deepcopy(data))
        ref=t.data.get('reference') or ''
        if not isinstance(ref,str) or len(ref)>192:fail('Old Reference must be text of at most 192 characters.')
        t.reference=ref
        t.currency=str(t.data.get('currency') or '').strip().upper()
        t.data['currency']=t.currency
        t.revenue_month=t.data.get('revenueMonth','')
        if not isinstance(t.revenue_month,str) or len(t.revenue_month)>7:fail('Invalid Revenue Month.')
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
        # Zero cash legs settle automatically, including a zero Swiss Cedant leg.
        # No review identity or bank receipt is fabricated.
        from .ledger import payload_for
        from cases.property_original import persist_settlements
        payload=payload_for(t)
        try:persist_settlements(payload,stamp.isoformat(),{'id':f'personnel:{person.pk}','name':person.name})
        except (ValueError,OverflowError):fail('The selected payment terms exceed the supported calendar range.')
        t.financial={key:copy.deepcopy(payload.get(key,{} if key=='swissAccounting' else []))
                     for key in ('paymentEntries','financeClaimTracking','swissAccounting','transactions')}

    else:fail('Unsupported transaction action.')
    t.version+=1;t.save()
    audit(person,t.pk,'draft_saved' if action=='save' else 'transaction_confirmed',before,state(t),str(t.data.get('claimReason') or ''))
    return t


def can_retract(person,t):
    if t.historical or t.status!='confirmed' or t.owner_id!=person.pk or person.role_code not in BUSINESS:return False
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
