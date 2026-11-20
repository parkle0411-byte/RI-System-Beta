"""2026-11-20 業主決定：所有向 Cedant 收款的帳款，Accounting 提醒日統一為實際到期前 15 天。
Swiss Property 原為 B＋80（到期前 10 天），改為 B＋75；含 Swiss Re 的案件，其他再保人份額的 Cedant 帳款也一樣。
純計算，不寫資料庫。"""
from datetime import date, datetime
from cases.property_original import transactions
from cases.calc.payment_terms import build_payment_schedule
from reminders.messages import SWISS_CEDANT_RULES
checks = []
def check(name, ok, detail=''):
    assert ok, (name, detail)
    checks.append(name); print('PASS ' + name, flush=True)

NAMES = {'Swiss': 'Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)', 'GA': 'Great American Insurance Company, Singapore Branch (Facility)',
         'Allianz': 'Allianz Global Corporate & Specialty SE, Hong Kong Branch (Facility)', 'QBE': 'QBE Hongkong & Shanghai Insurance Limited (Facility)',
         'AUW': "Lloyd's Underwriter Syndicate No. 0609 AUW (Facility)", 'Ordinary': 'QA Ordinary Re'}
def case(names, klass='Property', start='2026-11-05'):
    p = {'currency': 'USD', 'reinsured': 'QA Cedant', 'classCode': 'PD' if klass == 'Property' else 'GL', 'classOfBusiness': klass, 'reinsuranceStructure': 'QS',
         'policyFrom': start, 'policyTo': '2027-11-05', 'paymentTermsDays': 90, 'originalPremium': 1000, 'riCommPct': 0, 'taxPct': 0,
         'premiumLedgerLayout': 'per-reinsurer-v1', 'accountingRules': 'accounting-v1', 'paymentEntries': [], 'claims': [], 'twRef': 'QA-CR15', 'announcedAt': start + 'T00:00:00Z',
         'reinsurers': [{'name': NAMES[n], 'sharePct': round(100 / len(names), 4), 'premium': round(1000 / len(names), 2), 'riCommPct': 20, 'taxPct': 0, 'paymentTermsDays': 90} for n in names]}
    p['transactions'] = transactions(p, start + 'T00:00:00Z')
    return build_payment_schedule(p, datetime(2026, 11, 20, 4))['items']
def gap(item):
    return (date.fromisoformat(item['contractDueDate']) - date.fromisoformat(item['dueDate'])).days

# 例：TWPF2611001（2026-11-05 生效，Swiss Re＋Great American）→ 到期 2027-02-03、提醒 2027-01-19
items = [i for i in case(['Swiss', 'GA']) if i['partyType'] == 'cedant']
check('Swiss＋Great American 的 Property：Cedant 到期 2027-02-03、Accounting 提醒 2027-01-19（到期前 15 天）',
      items and all(i['contractDueDate'] == '2027-02-03' and i['dueDate'] == '2027-01-19' for i in items), items)
check('規則名稱改為 swiss_cedant_75_90，提醒信仍認得舊名稱', all(i['paymentRule'] == 'swiss_cedant_75_90' for i in items) and 'swiss_cedant_80_90' in SWISS_CEDANT_RULES)
for label, names, klass in [('只有 Swiss Re 的 Property', ['Swiss'], 'Property'), ('Great American', ['GA'], 'Property'), ('Allianz', ['Allianz'], 'Property'),
                            ('QBE', ['QBE'], 'Property'), ('AUW', ['AUW'], 'Property'), ('一般再保人', ['Ordinary'], 'Property'),
                            ('Swiss CGL QS', ['Swiss'], 'Commercial General Liability')]:
    cedants = [i for i in case(names, klass) if i['partyType'] == 'cedant']
    check(label + '：所有 Cedant 應收的 Accounting 提醒日都是到期前 15 天', cedants and all(gap(i) == 15 for i in cedants), [(i['dueDate'], i['contractDueDate']) for i in cedants])
print(f'{len(checks)}/{len(checks)} passed（Cedant 提醒日統一到期前 15 天）')
