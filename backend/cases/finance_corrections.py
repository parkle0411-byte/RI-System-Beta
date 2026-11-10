"""Version financial accounts without overwriting closed Production or review history."""
import copy
import uuid

from .cash_ledger import cents, objects, transaction_details


def base_no(tx):
    return tx.get('financeBaseNo') or tx.get('txNo')


def material(old, new, old_currency, new_currency):
    return (new is None or cents(old.get('amount', 0)) != cents(new.get('amount', 0)) or
            old.get('reinsurer') != new.get('reinsurer') or old.get('reinsurerName') != new.get('reinsurerName') or
            old_currency != new_currency)


def review_change_error(case, old, proposed):
    from .finance_workflow import active_reviews
    prior = {t.get('txNo'): t for t in objects(old.get('transactions'))}
    fresh = {t.get('txNo'): t for t in objects(proposed.get('transactions'))}
    reviewed = active_reviews({str(case.case_uid)})
    for (uid, no), pair in reviewed.items():
        before = prior.get(no)
        if before and (material(before, fresh.get(no), old.get('currency'), proposed.get('currency')) or old.get('reinsured') != proposed.get('reinsured')):
            return 'Cancel the entire Finance review batch for this account in Accounting before changing any member amount or counterparty. Reverse its active registrations first.'
    return ''


def correct_accounts(case, p, old, old_live, expected, old_details, changed, actor, now, reason):
    from .property_original import totals, report_amounts, persist_settlements
    from production.models import ProductionReport
    if changed & {'ae', 'splitParties', 'splitEnabled', 'installmentEnabled'} and (old.get('confirmedProductionKeys') or any(
            d.get('cashTracking') == 'derived' and d.get('settlement') == 'settled' for d in old_details.values())):
        return 'Account Executive, staff split and installment layout are locked after Production recognition or completed brokerage; use an endorsement.'
    by_base = {base_no(t): t for t in old_live}
    expected_by_base = {base_no(t): t for t in expected}
    if changed & {'policyFrom', 'policyTo', 'paymentTermsDays', 'performanceInstallments', 'reinsurers'}:
        from .calc.payment_terms import build_payment_schedule
        from .property_original import periods
        before_schedule = {x['scheduleKey']:x for x in build_payment_schedule(old)['items']}
        after_schedule = {x['scheduleKey']:x for x in build_payment_schedule(p)['items']}
        for tx in old_live:
            d = old_details.get(tx['txNo'], {})
            if d.get('cashTracking') == 'derived' or abs(d.get('paid', 0)) < .005:
                continue
            for part in d.get('cashParts', []):
                before = before_schedule.get(part['scheduleKey'], {})
                after = after_schedule.get(part['scheduleKey'], {})
                if any(before.get(k) != after.get(k) for k in ('baseDate','dueDate','contractDueDate','termsDays')):
                    return 'Payment terms and dates of an account with effective receipt/payment or offsets are locked; use an endorsement.'
            if changed & {'policyFrom', 'policyTo'} and (p.get('policyFrom'),p.get('policyTo')) != (old.get('policyFrom'),old.get('policyTo')):
                return 'The policy period is locked by an effective receipt/payment; use an endorsement.'
    changed_bases = {no for no, t in by_base.items() if material(t, expected_by_base.get(no), old.get('currency'), p.get('currency'))}
    changed_bases.update(no for no in expected_by_base if no not in by_base)
    if not changed_bases:
        # Non-money edits keep the exact existing ledger, including posting/frozen dates.
        proposed = {**p, 'transactions': copy.deepcopy(old.get('transactions') or [])}
        error = review_change_error(case, old, proposed)
        if error:
            return error
        p['transactions'] = proposed['transactions']
    else:
        proposed_live = []
        for t in expected:
            prior = by_base.get(base_no(t))
            proposed_live.append({**t, 'txNo': prior['txNo']} if prior else t)
        error = review_change_error(case, old, {**p, 'transactions': proposed_live})
        if error:
            return error
        for no in changed_bases:
            t = by_base.get(no)
            if not t:
                continue
            d = old_details.get(t['txNo'], {})
            # Reversed historical registrations do not lock a currently untreated account.
            if d.get('cashTracking') != 'derived' and abs(d.get('paid', 0)) > .004:
                return 'An account with an active receipt/payment or offset cannot change. Use an endorsement or reverse the complete registration first.'
            if d.get('cashTracking') == 'derived' and d.get('settlement') == 'settled' and abs(d.get('paid', 0)) > .004:
                return 'This reinsurer account is already completed. Use an endorsement.'
        pairs = {(t.get('installmentId') if old.get('installmentEnabled') else 'FULL', t.get('reinsurerIdx'))
                 for t in old_live if base_no(t) in changed_bases}
        # Preserved aggregate T1/T3 spans the reinsurers' individual Production rows.
        for t in old_live:
            if base_no(t) in changed_bases and t.get('caseAggregate'):
                period = t.get('installmentId') if old.get('installmentEnabled') else 'FULL'
                pairs.update((period, i) for i in range(len(objects(old.get('reinsurers')))))
        # Staff/period reshaping is never used to rewrite a recognized distribution.
        if changed & {'ae', 'splitParties', 'splitEnabled', 'installmentEnabled'} and old.get('confirmedProductionKeys'):
            return 'Keep recognized staff and installment allocations unchanged; use an endorsement.'
        closed_months = set(ProductionReport.objects.filter(status='closed').values_list('year_month', flat=True))
        histories = [h for h in objects(old.get('productionHistory')) if h.get('cycle', 0) == int(old.get('reversalCycle') or 0) and not h.get('isReversal')]
        # Latest effective corrected snapshots supersede the source snapshot for later corrections.
        snapshots = {h['row']['id']: h['row'] for h in histories if isinstance(h.get('row'), dict)}
        for history in objects(old.get('financeCorrectionHistory')):
            for row in history.get('productionEffectiveRows', []):
                snapshots[row.get('financeSourceId', row['id'])] = row
        affected = []
        for source_id, row in snapshots.items():
            try:
                stem, idx = row.get('financeSourceKey', row['reinsurerKey']).rsplit(':R', 1)
                period = stem.split(':', 1)[1]; idx = int(idx)
            except (KeyError, ValueError):
                return 'Review the stored Production allocation before changing this account.'
            if (period, idx) in pairs:
                affected.append((source_id, row, period, idx))
        closed_pairs = {(period, idx) for source_id, row, period, idx in affected if row.get('financeOriginalMonth', row.get('month')) in closed_months}
        revision = len(objects(old.get('financeCorrectionHistory'))) + 1
        correction_id = str(uuid.uuid4()); rows_out = []; effective = []; closed_ledger_periods = set()
        from production.calc import next_production_month
        from .calc.swiss_facility import local_date
        target_month = local_date(now)[:7]
        while target_month in closed_months:
            target_month = next_production_month(target_month)
        for source_id, row, period, idx in affected:
            try:
                person_index = int(source_id.rsplit(':P', 1)[1])
                new_premiums, new_incomes = report_amounts(p, period, row['rate'])[idx]
                premium, income = new_premiums[person_index], new_incomes[person_index]
            except (KeyError, IndexError, ValueError, StopIteration):
                return 'Keep the original recognized staff and reinsurer allocations identifiable.'
            if (premium, income) == (row['premium'], row['income']):
                continue
            if (period, idx) in closed_pairs:
                closed_ledger_periods.add(period)
                common = {**copy.deepcopy(row), 'financeSourceId': source_id,
                    'financeSourceKey': row.get('financeSourceKey', row['reinsurerKey']),
                    'financeOriginalMonth': row.get('financeOriginalMonth', row.get('month')),
                    'financeCorrectionId': correction_id, 'correctionBatchId': correction_id,
                    'isProductionReversal': True, 'reversalCycle': int(old.get('reversalCycle') or 0),
                    'month': target_month, 'exclusion': None}
                old_row = {**common, 'id': source_id + ':FC' + str(revision) + '-OLD',
                           'premium': -row['premium'], 'income': -row['income'], 'financeCorrectionSide': 'reversal'}
                new_row = {**common, 'id': source_id + ':FC' + str(revision) + '-NEW',
                           'premium': premium, 'income': income, 'financeCorrectionSide': 'replacement'}
                rows_out.extend([old_row, new_row]); effective.append(new_row)
        if rows_out:
            p.setdefault('productionReversals', []).append({'cycle': int(old.get('reversalCycle') or 0),
                'financeCorrectionId': correction_id, 'month': target_month, 'rows': rows_out, 'confirmedKeys': []})
        # Retain unchanged rows exactly. Version only modified accounts belonging to closed Production.
        ledger = [copy.deepcopy(t) for t in objects(old.get('transactions')) if t not in old_live]
        ledger_changes = []
        date_fields = ('baseDate', 'dueDate', 'contractDueDate', 'termsDays', 'reminderDate', 'paymentRule')
        for no, prior in by_base.items():
            replacement = expected_by_base.get(no)
            if no not in changed_bases:
                ledger.append(copy.deepcopy(prior)); continue
            d = old_details.get(prior['txNo'], {})
            dates = {k: d[k] for k in date_fields if k in d}
            pair = (prior.get('installmentId') if old.get('installmentEnabled') else 'FULL', prior.get('reinsurerIdx'))
            if pair in closed_pairs or prior.get('caseAggregate') and pair[0] in closed_ledger_periods:
                original = {**copy.deepcopy(prior), 'reversed': True, 'financeCorrectionId': correction_id,
                            'financeSuperseded': True}
                reversal = {**copy.deepcopy(prior), 'txNo': prior['txNo'] + '-RVS' + str(revision),
                    'amount': -prior['amount'], 'reversed': False, 'isReversalEntry': True,
                    'financeCorrectionId': correction_id, 'financeReversalOf': prior['txNo'],
                    'createdAt': now, 'financeDates': dates}
                ledger.extend([original, reversal])
                if replacement:
                    new = {**replacement, 'txNo': no + '-ADJ' + str(revision), 'financeBaseNo': no,
                        'financeCorrectionId': correction_id, 'financePreviousTxNo': prior['txNo'],
                        'financeDates': dates, 'postedMonth': prior.get('postedMonth', ''),
                        'postingFxRate': prior.get('postingFxRate'), 'productionRecognized': prior.get('productionRecognized', False)}
                    ledger.append(new)
                    original['financeReplacementTxNo'] = new['txNo']; reversal['financeReplacementTxNo'] = new['txNo']
            elif replacement:
                ledger.append({**replacement, 'txNo': prior['txNo'], 'financeBaseNo': no, 'financeDates': dates,
                               'financeReopened': True})
            ledger_changes.append({'before': copy.deepcopy(prior), 'after': copy.deepcopy(replacement)})
        for no, new in expected_by_base.items():
            if no not in by_base:
                ledger.append(new)
        p['transactions'] = ledger
        p.setdefault('financeCorrectionHistory', []).append({'id': correction_id, 'revision': revision,
            'at': now, 'by': actor['id'], 'byName': actor['name'], 'reason': reason,
            'ledgerChanges': ledger_changes, 'productionEffectiveRows': effective,
            'productionMonth': target_month if rows_out else '', 'originalRatesRetained': True})
    changes = {k: {'before': copy.deepcopy(old.get(k)), 'after': copy.deepcopy(p.get(k))} for k in sorted(changed)}
    p.setdefault('propertyEditHistory', []).append({'at': now, 'by': actor['id'], 'byName': actor['name'],
        'reason': reason, 'changes': changes, 'amountsBefore': totals(old), 'amountsAfter': totals(p)})
    persist_settlements(p, now, actor)
    return ''
