"""Shared Legacy read and permanent audit helpers."""
import copy
from django.db import transaction
from ri_system.authz import AuthError
from .models import LegacyAudit


def fail(message,status=400,code='legacy_invalid'):
    raise AuthError(status,code,message)


def audit(person,entity,action,before=None,after=None,reason=''):
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError('Legacy audit must be part of the business transaction.')
    LegacyAudit.objects.create(entity=str(entity),action=action,actor_id=person.pk,actor_name=person.name,
        reason=reason,before=before or {},after=after or {})


def state(t):
    return dict(uid=str(t.uid),number=t.number,status=t.status,version=t.version,
        ownerId=t.owner_id,data=copy.deepcopy(t.data),financial=copy.deepcopy(t.financial),
        fxSnapshot=copy.deepcopy(t.fx_snapshot))


def representation(t,person=None):
    result=state(t)
    result.update(reference=t.reference,currency=t.currency,revenueMonth=t.revenue_month,
        historical=t.historical,imported=bool(t.batch_id),originalSerial=t.original_serial,operation=t.operation,
        referenceTransaction=str(t.reference_transaction_id or ''),corrects='',performance=rate_for(t),
        createdAt=t.created_at.isoformat(),firstConfirmedAt=t.first_confirmed_at.isoformat() if t.first_confirmed_at else '',
        permissions=dict(edit=False,confirm=False,correct=False,transfer=False,retract=False),readOnly=True)
    if t.reference_transaction_id:
        source=t.reference_transaction
        result['referenceSource']=dict(uid=str(source.uid),number=source.number,reference=t.data.get('sourceReference',source.reference))
    if not t.historical:
        allowed = bool(person and person.role_code in ('sales','general_manager','admin') and t.owner_id == person.pk and t.status == 'draft')
        result['permissions'].update(edit=allowed, confirm=allowed)
        if person:
            from .entries import can_retract,can_transfer
            result['permissions']['retract']=can_retract(person,t)
            result['permissions']['transfer']=can_transfer(person,t)
        result['readOnly'] = not allowed
        if t.status == 'draft':
            from .entries import locked_fields
            result['lockedFields'] = sorted(locked_fields(t.data))
            if t.data.get('kind') == 'endorsement' and t.data.get('effectiveDate'):
                from .policy import revenue_month
                result['projectedRevenueMonth'] = revenue_month(t.data.get('effectiveDate'))
            from .money import calculate
            try: result['amountsPreview'] = calculate(t.data)
            except ValueError as exc: result['calculationError'] = str(exc)
    return result


def rate_for(t):
    if t.historical or t.fx_snapshot:
        return copy.deepcopy(t.fx_snapshot)
    if t.status != 'confirmed' or t.data.get('kind') == 'claim':
        return {}
    from fxrates.models import FxRate
    from .money import split_performance
    rate = 1 if t.currency == 'TWD' else FxRate.objects.filter(year_month=t.revenue_month,currency=t.currency).values_list('rate',flat=True).first()
    return split_performance(t.data,t.data['amounts'],None if rate is None else float(rate))


def contains_legacy_reference(body):
    """Reject legacy or mixed finance writes before native transaction handlers."""
    import uuid
    from .models import LegacyTransaction
    ids=set();pending=[body]
    while pending:
        value=pending.pop()
        if isinstance(value,dict):
            for key,item in value.items():
                if key in ('caseUid','case_uid','legacyTransactionId') and isinstance(item,str):
                    try:ids.add(uuid.UUID(item))
                    except ValueError:pass
                elif isinstance(item,(dict,list)):pending.append(item)
        elif isinstance(value,list):pending.extend(value)
    return bool(ids and LegacyTransaction.objects.filter(pk__in=ids,historical=True).exists())
