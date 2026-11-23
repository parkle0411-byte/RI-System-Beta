"""Produce immutable declaration accounting facts before ledger registration.

The caller must snapshot the returned facts with the declaration. This module
does not write accounting, Production, cash or close history.
"""
from decimal import Decimal
from .facility_placement import calculate


def _direction(net, cedant):
    value = Decimal(str(net))
    if value == 0:
        return 'none'
    return ('receivable' if value > 0 else 'payable') if cedant else ('payable' if value > 0 else 'receivable')


def settlement_plan(facility, declaration):
    """Calculate one Cedant line per reinsurer and one Reinsurer line.

    Premium and Claim remain separate facts while each party's net combines
    them. Reinsurer reference and Statement No. are captured in each snapshot.
    """
    rows = calculate(facility, declaration['premium'], declaration['claim'])
    result = []
    for index, row in enumerate(rows):
        common = {'reinsurerIndex': index, 'reinsurer': row['name'],
                  'reinsurerReference': row['reference'], 'statementNo': declaration['statementNo'],
                  'currency': facility['currency'], 'periodFrom': declaration['periodFrom'],
                  'periodTo': declaration['periodTo'], 'dueDate': declaration['dueDate'],
                  'premium': row['premium'], 'claim': row['claim'], 'brokerage': row['brokerage']}
        result.append({**common, 'partyType': 'cedant', 'partyName': facility['reinsured'],
                       'commission': row['cedantCommission'], 'tax': row['cedantTax'],
                       'net': row['cedantNet'], 'direction': _direction(row['cedantNet'], True)})
        result.append({**common, 'partyType': 'reinsurer', 'partyName': row['name'],
                       'deduction': row['deduction'], 'tax': row['reinsurerTax'],
                       'net': row['reinsurerNet'], 'direction': _direction(row['reinsurerNet'], False)})
    return result


def transactions(facility, declaration, declaration_uid, timestamp, revenue_month):
    """Create per-counterparty net transactions; preserve underlying components."""
    plan = settlement_plan(facility, declaration)
    result = []
    for index in range(0, len(plan), 2):
        cedant, reinsurer = plan[index:index + 2]
        ordinal = cedant['reinsurerIndex'] + 1
        base = f"{facility['twRef']}-D{declaration_uid}-R{ordinal}"
        common = {'facilityNet': True, 'declarationUid': str(declaration_uid),
                  'installmentId': str(declaration_uid),
                  'facilityStatementNo': declaration['statementNo'], 'reinsurerIdx': ordinal - 1,
                  'reinsurer': reinsurer['partyName'], 'source': 'premium', 'createdAt': timestamp,
                  'postedMonth': revenue_month, 'productionRecognized': False, 'settlement': 'open',
                  'baseDate': declaration['periodTo'], 'dueDate': declaration['dueDate'],
                  'facilityPeriodFrom': declaration['periodFrom'], 'facilityPeriodTo': declaration['periodTo'],
                  'facilityPremium': cedant['premium'], 'facilityClaim': cedant['claim']}
        for number, row in ((1, cedant), (2, reinsurer)):
            result.append({**common, 'txNo': f'{base}-T{number}', 'legType': f'Leg {number}',
                           'label': 'Facility declaration', 'amount': row['net']})
        result.append({**common, 'txNo': f'{base}-T3', 'legType': 'Leg 3',
                       'label': 'Brokerage retained', 'amount': cedant['brokerage']})
    return result


def corrected_transactions(existing, replacement, revision, closed):
    """Return a new ledger preserving closed history; callers must hold the case lock.

    Existing cash and review activity must be checked by the caller before use.
    A closed correction retains originals and explicit opposite entries, then
    appends replacement legs with new unique numbers.
    """
    if type(revision) is not int or revision < 1:
        raise ValueError('A positive correction revision is required.')
    if not closed:
        old = {row['txNo']: row for row in existing}
        return [{**row, 'txNo': old[row['txNo']]['txNo']} if row['txNo'] in old else row for row in replacement]
    output = []
    for row in existing:
        if row.get('reversed') or row.get('isReversalEntry'):
            raise ValueError('Only active transaction legs may be corrected.')
        output.append({**row, 'reversed': True})
        output.append({**row, 'txNo': f"{row['txNo']}-COR{revision}-REV",
                       'amount': -row['amount'], 'reversed': False, 'isReversalEntry': True,
                       'reversalOf': row['txNo'], 'settlement': 'open'})
    output.extend({**row, 'txNo': f"{row['txNo']}-COR{revision}-NEW", 'correctionRevision': revision} for row in replacement)
    return output
