"""Oversea Business: independent brokerage with no cedant/reinsurer premium legs."""
CLASSES = ('Fine Art', 'Terrorism')


def enabled(payload):
    return isinstance(payload, dict) and str(payload.get('reinsuranceStructure') or '').strip().upper() == 'OVERSEA'


def issues(payload, ready=False):
    if not enabled(payload):
        return []
    from .data_integrity import financial_issues
    from datetime import date
    result = financial_issues(payload)
    def add(field, label):
        result.append({'field': field, 'label': label})
    klass = payload.get('classOfBusiness')
    if klass and klass not in CLASSES or ready and not klass:
        add('classOfBusiness', 'Oversea Business supports Fine Art and Terrorism only.')
    from decimal import Decimal, InvalidOperation
    for field, raw in [('originalPremium', payload.get('originalPremium')), *[(f'reinsurers.{i}.brokerageAmount', r.get('brokerageAmount')) for i,r in enumerate(payload.get('reinsurers') or []) if isinstance(r,dict)]]:
        if raw is None or str(raw).strip() == '':
            continue
        try:
            number = Decimal(str(raw))
            unit = Decimal('1') if payload.get('currency') == 'TWD' else Decimal('.01')
            if number.is_finite() and number != number.quantize(unit):
                add(field, ('100% Premium' if field == 'originalPremium' else 'Brokerage') + (' must be a whole number for TWD.' if payload.get('currency') == 'TWD' else ' must have at most two decimal places.'))
        except (ValueError, InvalidOperation):
            pass
    rows = payload.get('reinsurers')
    if rows is not None and (not isinstance(rows,list) or len(rows) > 1):
        add('reinsurers', 'Select one Reinsurance Broker for Oversea Business.')
    if payload.get('splitEnabled'):
        add('reinsuranceStructure', 'Oversea Business does not support staff splitting.')
    if payload.get('parentTwRef') and payload.get('installmentEnabled'):
        add('installmentEnabled', 'Endorsements use one T3 brokerage movement.')
    rows = payload.get('performanceInstallments') or []
    if payload.get('installmentEnabled'):
        ids = [str(r.get('id') or '') for r in rows if isinstance(r, dict)]
        if len(ids) != len(set(ids)):
            add('performanceInstallments', 'Installment IDs must be unique.')
    if not ready:
        return result
    if payload.get('installmentEnabled'):
        if len(rows) < 2:
            add('performanceInstallments', 'Use at least two installments.')
        ratios = []
        for i, row in enumerate(rows):
            if not isinstance(row,dict):
                add('performanceInstallments', 'Invalid installment.');continue
            raw = row.get('ratio')
            try:
                ratio = float(raw)
                if isinstance(raw,bool) or not 0 < ratio <= 100:raise ValueError()
                ratios.append(ratio)
            except (TypeError,ValueError):add(f'performanceInstallments.{i}.ratio', 'Enter an installment ratio greater than 0 and at most 100%.')
            stamp = row.get('paymentBaseDate')
            try:
                if date.fromisoformat(stamp).isoformat()!=stamp:raise ValueError()
            except (TypeError,ValueError):add(f'performanceInstallments.{i}.paymentBaseDate', 'Each installment requires an actual Receipt / Payment Date.')
        if len(ratios)==len(rows) and abs(sum(ratios)-100)>0.000001:
            add('performanceInstallments', 'Installment ratios must total 100%.')
    if payload.get('parentTwRef'):
        for key,label in [('endoEffectiveDate','Endorsement Effective Date'),('endoText','Endorsement Description')]:
            if not str(payload.get(key) or '').strip():add(key,label+' is required.')
    for key, label in [('originalInsured', 'Insured (EN)'), ('originalInsuredCn', 'Insured (CN)'), ('policyFrom', 'Effective Date'), ('policyTo', 'Expiration Date'), ('ae', 'Account Executive'), ('reinsured', 'Cedant'), ('currency', 'Currency'), ('originalPremium', '100% Premium'), ('receiptPaymentDate', 'Receipt / Payment Date')]:
        if key == 'receiptPaymentDate' and payload.get('installmentEnabled'):continue
        if payload.get(key) is None or str(payload.get(key)).strip() == '':
            add(key, label + ' is required.')
    stamp = payload.get('receiptPaymentDate')
    if stamp:
        try:
            if date.fromisoformat(stamp).isoformat() != stamp:
                raise ValueError()
        except (TypeError, ValueError):
            add('receiptPaymentDate', 'Receipt / Payment Date must use YYYY-MM-DD.')
    rows = payload.get('reinsurers') or []
    if len(rows) != 1:
        add('reinsurers', 'Select one Reinsurance Broker for Oversea Business.')
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        for key, label in [('name', 'Reinsurance Broker'), ('sharePct', 'Share (%)'), ('brokerageAmount', 'Brokerage')]:
            if row.get(key) is None or str(row.get(key)).strip() == '':
                add(f'reinsurers.{i}.{key}', label + ' is required.')
        try:
            if row.get('sharePct') is not None and not 0 < float(row['sharePct']) <= 100:
                add(f'reinsurers.{i}.sharePct', 'Share must be greater than 0 and at most 100%.')
        except (TypeError, ValueError):
            pass
    return result


def legs(payload, reinsurer):
    from .calc.accounting import number_or_zero
    from .calc.premium_money import premium_money, premium_source
    round_money = lambda value: premium_money(value, payload)
    premium = round_money(premium_source(number_or_zero(payload.get('originalPremium')), payload) * number_or_zero(reinsurer.get('sharePct')) / 100)
    if payload.get('parentTwRef'):premium=0
    brokerage = round_money(number_or_zero(reinsurer.get('brokerageAmount')))
    return dict(cp=premium, ri=0, tax=0, leg1=0, reinsurerCp=0, reinsurerRi=0, reinsurerTax=0, leg2=0, leg3=brokerage, brokerage=brokerage)


def dates(payload, transaction=None):
    from datetime import date, timedelta
    stamp = payload.get('receiptPaymentDate')
    if transaction and transaction.get('installmentId'):
        row=next((r for r in payload.get('performanceInstallments') or [] if isinstance(r,dict) and r.get('id')==transaction['installmentId']),{})
        stamp=row.get('paymentBaseDate')
    try:
        actual = date.fromisoformat(stamp)
        accounting = actual - timedelta(days=10)
    except (TypeError, ValueError, OverflowError):
        return dict(baseDate='', dueDate='', contractDueDate='', actualPaymentDate='', accountingDate='', paymentRule='oversea_actual_minus_10')
    return dict(baseDate=stamp, dueDate=accounting.isoformat(), contractDueDate=stamp, actualPaymentDate=stamp, accountingDate=accounting.isoformat(), paymentRule='oversea_actual_minus_10')


def refresh_transactions(payload, reference, now):
    """Announce creates only the single T3; Finance records actual cash separately."""
    from .calc.accounting import build_premium_transactions
    payload.update(twRef=reference, announcedAt=payload.get('announcedAt') or now, postedAt=payload.get('postedAt') or now)
    previous = {t['txNo']:t for t in payload.get('transactions') or [] if isinstance(t,dict) and t.get('txNo')}
    expected = build_premium_transactions(payload)
    result = []
    for tx in expected:
        old = previous.get(tx['txNo'])
        if old and old.get('amount') == tx['amount'] and old.get('reinsurer') == tx['reinsurer'] and old.get('installmentId') == tx.get('installmentId'):
            tx = {**tx, **old, **dates(payload, tx)}
        result.append(tx)
    payload['transactions'] = result


def edit_error(case, payload, body):
    old = case.payload or {}
    if case.status == 'draft':
        return ''
    if enabled(old) != enabled(payload):
        return 'The Reinsurance Type is locked after Announce.'
    if not enabled(old):
        return ''
    fields = ('currency','classOfBusiness','classCode','reinsured','originalPremium','reinsurers','receiptPaymentDate','ae','installmentEnabled','performanceInstallments')
    if not any(old.get(k) != payload.get(k) for k in fields):
        return ''
    if old.get('confirmedProductionKeys'):
        return 'Recognized Oversea Business facts are locked.'
    from .finance_workflow import active_reviews
    if active_reviews({str(case.case_uid)}):
        return 'Cancel the Finance review before changing Oversea Business facts.'
    from .cash_ledger import transaction_details
    if any(abs(d.get('paid',0)) > .004 for d in transaction_details(old).values()):
        return 'Reverse active receipts or payments before changing Oversea Business facts.'
    if not str(body.get('reason') or '').strip():
        return 'Enter a reason for changing Oversea Business facts.'
    return ''


def periods(payload):
    """One authoritative ratio allocation shared by ledger and production."""
    from .calc.payment_terms import allocate
    from .calc.accounting import number_or_zero
    rows=payload.get('performanceInstallments') or [] if payload.get('installmentEnabled') else []
    total=sum(legs(payload,r)['brokerage'] for r in payload.get('reinsurers') or [])
    if not rows:return [dict(id='FULL',number=1,label='Full',ratio=100,amount=total,**dates(payload))]
    weights=[dict(weight=number_or_zero(r.get('ratio'))) for r in rows]
    amounts=allocate(abs(total),weights,payload)
    if total<0:amounts=[-value if value else 0 for value in amounts]
    return [dict(id=r.get('id') or f'I{i+1}',number=i+1,label=f'Installment {i+1}',ratio=r.get('ratio'),amount=amounts[i],**dates(payload,{'installmentId':r.get('id')})) for i,r in enumerate(rows)]


def broker_note_kinds(payload):
    return ('broker_credit', 'broker_debit') if payload.get('parentTwRef') else ('broker_credit',)


def broker_note_coverage(payload, files):
    selected = [f for f in files if f.get('is_selected')]
    ready = any(f.get('kind') in broker_note_kinds(payload) and f.get('contentAvailable', True) for f in selected)
    return dict(offer=False, required=[], covered=[], missing=[], ready=ready,
                selected=[str(f['id']) for f in selected],
                brokerNoteRequired=True, brokerNoteReady=ready,
                brokerNoteKinds=list(broker_note_kinds(payload)))
