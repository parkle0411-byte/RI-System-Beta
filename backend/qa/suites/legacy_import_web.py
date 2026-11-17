from qa.accounting_full import accounting_get   # 2026-11-17: retired Accounting reads are internal in tests
"""Web import of reinsurer Registers (owner decisions 2026-11-11). Synthetic workbook, disposable MySQL only.

Covers: admin-only two-step import; errors and warnings block the commit; PD + GL; owner corrections and
exclusions; Class codes from MDM (PD = PF, inactive and non-Property Facility warn); per-side settlement from the Register receipt/payment numbers (Accounting Dept. Ref.);
claim settlement on the last day of Closed Month; fully settled rows stay historical; rows with an open
side continue in the native Finance workflow; settled-before-import receipts cannot be reversed; imported
rows never feed Production, cannot be retracted, and native records stay unchanged; duplicates are skipped.
"""
import io, json, os, zipfile
from xml.sax.saxutils import escape
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client
from cases import storage
from cases.models import Case, FinanceReconciliationBatch
from legacy.models import ImportBatch, LegacyTransaction, LegacyAudit
from masterdata.models import MasterRecord
from personnel.models import Personnel
from production.models import ProductionReport

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks = []
def check(name, value, detail=''):
    assert value, (name, detail)
    checks.append(name); print('PASS ' + name, flush=True)

HEAD = ['流水號', 'Insured (in English)', 'Insured (in Chinese)', 'Year ', 'Endorsement No.', 'Class', 'TW Ref. No.', 'Reinsurer',
        "Reinsurer's Ref. No.", 'Cedant', "Cedant's Policy No.", 'Effective Date', 'Expiry Date', 'AE', 'Sub AE', 'Issue Date of Claim',
        'DOL', 'Currency', '100%Premium', 'Share', 'Our Share Premium', 'R/I Comm.', 'Claim', 'Note for Claim', 'Tax', 'Bkg.(%)',
        'Note for Bkg.', 'Bkg.\n(Original Currency)', 'Bkg. (in TWD)', 'Re Dept. Bkg.\n(in TWD)', 'Net Premium from Cedant',
        'Net Premium to Reinsurer', 'Revenue Month', 'Exchange Rate', 'New / Renew', 'Fac / Claim', 'Payment Split', 'Receive Date',
        'Pay Date', 'Remark', ' Cedant Receipt No', ' Cedant Payment No', ' Reinsurer Receipt No', ' Reinsurer Payment No.',
        'closed', 'Closed Month', 'Full-closed']
FAC = 'Allianz Global Corporate & Specialty SE, Hong Kong Branch (Facility)'
ORD = 'QA Ordinary Reinsurer Ltd.'
D = lambda iso: str((__import__('datetime').date.fromisoformat(iso) - __import__('datetime').date(1899, 12, 30)).days)

def row(serial, **kw):
    base = {'流水號': serial, 'Insured (in English)': 'QA Insured ' + serial, 'Insured (in Chinese)': '測試' + serial, 'Year ': '2026',
            'Class': 'PD', 'TW Ref. No.': 'TWQA-' + serial, 'Reinsurer': FAC, 'Cedant': 'QA Cedant', "Cedant's Policy No.": 'SOA-' + serial,
            'Effective Date': D('2026-03-01'), 'Expiry Date': D('2027-03-01'), 'AE': 'QA AE', 'Currency': 'TWD', '100%Premium': '20000',
            'Share': '0.5', 'Our Share Premium': '10000', 'R/I Comm.': '1500', 'Claim': '0', 'Tax': '100', 'Bkg.(%)': '0.2',
            'Bkg.\n(Original Currency)': '2000', 'Bkg. (in TWD)': '2000', 'Re Dept. Bkg.\n(in TWD)': '2000',
            'Net Premium from Cedant': '8400', 'Net Premium to Reinsurer': '6400', 'Revenue Month': D('2026-03-31'), 'Exchange Rate': '1',
            'New / Renew': 'New', 'Fac / Claim': 'Fac', 'Receive Date': D('2026-05-10'), 'Pay Date': D('2026-05-20')}
    base.update(kw)
    return {k: v for k, v in base.items() if v is not None}

def col(i):
    s = ''
    i += 1
    while i: i, r = divmod(i - 1, 26); s = chr(65 + r) + s
    return s

def workbook(rows):
    def cell(ref, value):
        if isinstance(value, tuple):  # (formula, cached value)
            return f'<c r="{ref}"><f>{escape(value[0])}</f><v>{escape(str(value[1]))}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>'
    lines = []
    for n, values in enumerate([dict(zip(HEAD, HEAD))] + rows, 1):
        lines.append(f'<row r="{n}">' + ''.join(cell(col(i) + str(n), values[h]) for i, h in enumerate(HEAD) if h in values) + '</row>')
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr('xl/workbook.xml', f'<?xml version="1.0"?><workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Facultative" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml', f'<?xml version="1.0"?><worksheet xmlns="{ns}"><sheetData>' + ''.join(lines) + '</sheetData></worksheet>')
    return out.getvalue()

ROWS = [
    row('QA9001', **{' Cedant Receipt No': 'CR-9001', ' Reinsurer Payment No.': 'RP-9001', 'closed': 'v', 'Full-closed': 'v'}),  # fully settled
    row('QA9002', **{' Cedant Receipt No': 'CR-9002'}),                                                                        # cedant only
    row('QA9003', Class='GL', Reinsurer=ORD, **{"Reinsurer's Ref. No.": 'RREF-9003'}),                                          # GL, open
    row('QA9004', **{'Fac / Claim': 'Claim', 'Claim': '5000', 'Our Share Premium': '0', 'R/I Comm.': '0', 'Tax': '0',
        'Bkg.\n(Original Currency)': '0', 'Bkg. (in TWD)': '0', 'Re Dept. Bkg.\n(in TWD)': '0', 'Bkg.(%)': '0',
        'Net Premium from Cedant': '-5000', 'Net Premium to Reinsurer': '-5000', 'Revenue Month': 'N/A', 'Receive Date': 'Claim',
        'Pay Date': 'Claim', 'DOL': D('2026-04-15'), ' Cedant Payment No': 'CP-9004', ' Reinsurer Receipt No': 'RR-9004',
        'Closed Month': D('2026-07-01'), 'closed': 'v', 'Full-closed': 'v'}),                                                    # settled claim
    row('QA9005', **{'Endorsement No.': 'E-01', 'Revenue Month': D('2026-09-30')}),                                             # endorsement, open
    row('QA9006', **{'Fac / Claim': 'Claim', 'Claim': '5000', 'Our Share Premium': '0', 'R/I Comm.': '0', 'Tax': '0',
        'Bkg.\n(Original Currency)': '0', 'Bkg. (in TWD)': '0', 'Re Dept. Bkg.\n(in TWD)': '0', 'Bkg.(%)': '0',
        'Net Premium from Cedant': '-5000', 'Net Premium to Reinsurer': '-5000', 'Revenue Month': 'N/A', 'Receive Date': 'Claim',
        'Pay Date': 'Claim', 'DOL': D('2026-04-15'), 'Issue Date of Claim': D('2026-10-13')}),                                    # open claim
    row('QA9007', **{'R/I Comm.': ('ROUND(U8*0.125,0)', '1250'), 'Tax': ('U8*0.01', '100'), 'Net Premium from Cedant': '8650', 'Net Premium to Reinsurer': '6650'}),  # formula rates
    row('F2898', **{'Fac / Claim': None, 'New / Renew': None, ' Cedant Receipt No': 'CR-2898', ' Reinsurer Payment No.': 'RP-2898'}),  # owner correction
    row('F13333'),                                                                                                             # owner exclusion
]
User = get_user_model()

class Rollback(Exception): pass
keys = []
try:
    with transaction.atomic():
        MasterRecord.objects.create(entity_type='reinsurer', name=ORD, payload={}, created_by='qa', updated_by='qa')
        # 2026-11-16: Register Class codes come from MDM Class (PD = PF Property).
        for code, name, active in (('PF', 'Property', True), ('GL', 'Commercial General Liability', True),
                                   ('QE', 'QA Engineering', True), ('QZ', 'QA Retired Class', False)):
            if not MasterRecord.objects.filter(entity_type='class', code=code, is_active=True).exists():
                MasterRecord.objects.create(entity_type='class', code=code, name=name, is_active=active, payload={}, created_by='qa', updated_by='qa')
        Personnel.objects.create(name='QA AE', department='reinsurance', role_code='sales', created_by='qa', updated_by='qa')
        clients = {}
        for role in ('admin', 'sales', 'accounting'):
            u = User.objects.create_user(username='qa-legimp-' + role, password='Legacy-Import-9!')
            p = Personnel.objects.create(name='QA LegImp ' + role, department='finance' if role == 'accounting' else 'reinsurance',
                                         role_code=role, auth_user_id=str(u.pk), account_status='active', created_by='qa', updated_by='qa')
            c = Client(HTTP_HOST='localhost'); c.force_login(u); clients[role] = c
        admin, fin = clients['admin'], clients['accounting']
        native = lambda: (Case.objects.count(), ProductionReport.objects.count(), FinanceReconciliationBatch.objects.count())
        before = native()
        upload = lambda c, content, name='QA Register.xlsx': c.post('/api/legacy/imports', {'file': SimpleUploadedFile(name, content)})
        commit = lambda c, b, sha=None: c.post('/api/legacy/imports', json.dumps({'action': 'commit', 'id': b['id'], 'sha256': sha or b['sha256']}), content_type='application/json')

        good = workbook(ROWS)
        for role in ('sales', 'accounting'):
            check(role + ' cannot preview an import', upload(clients[role], good).status_code == 403)
        check('anonymous cannot preview an import', upload(Client(HTTP_HOST='localhost'), good).status_code in (401, 403))

        r = upload(admin, workbook([row('QA9101', Class='XX')])); bad = r.json(); keys.append(ImportBatch.objects.get(pk=bad['id']).storage_key)
        check('row errors are listed', r.status_code == 201 and bad['manifest']['errors'][0]['message'].startswith('Class must be a Class code in Master Data Management'), bad)
        check('errors block the import', commit(admin, bad).status_code == 409)
        r = upload(admin, workbook([row('QA9102', Reinsurer='QA Unknown Reinsurer')])); warn = r.json(); keys.append(ImportBatch.objects.get(pk=warn['id']).storage_key)
        check('warnings are listed', warn['manifest']['warnings'] and not warn['manifest']['errors'], warn['manifest'])
        check('warnings block the import', commit(admin, warn).status_code == 409)
        r = upload(admin, workbook([row('QA9104', **{'Fac / Claim': 'Claim', 'Claim': '5000', 'Our Share Premium': '0', 'R/I Comm.': '0', 'Tax': '0',
        'Bkg.\n(Original Currency)': '0', 'Bkg. (in TWD)': '0', 'Re Dept. Bkg.\n(in TWD)': '0', 'Bkg.(%)': '0',
        'Net Premium from Cedant': '-5000', 'Net Premium to Reinsurer': '-5000', 'Revenue Month': 'N/A', 'Receive Date': 'Claim',
        'Pay Date': 'Claim', 'DOL': D('2026-04-15')})])); noissue = r.json(); keys.append(ImportBatch.objects.get(pk=noissue['id']).storage_key)
        check('an open claim without Issue Date of Claim is a blocking warning', 'Issue Date of Claim is required' in noissue['manifest']['warnings'][0]['message'], noissue['manifest'])
        r = upload(admin, workbook([row('QA9105', **{'R/I Comm.': ('ROUND(U2*0.1,0)', '1500')})])); badrate = r.json(); keys.append(ImportBatch.objects.get(pk=badrate['id']).storage_key)
        check('a commission amount that is not premium x formula rate is a blocking warning', 'R/I Comm. does not equal' in badrate['manifest']['warnings'][0]['message'], badrate['manifest'])
        r = upload(admin, workbook([row('QA9108', Class='QZ', Reinsurer=ORD)])); inactive = r.json(); keys.append(ImportBatch.objects.get(pk=inactive['id']).storage_key)
        check('an inactive MDM Class is a blocking warning', not inactive['manifest']['errors'] and 'is inactive in Master Data Management' in inactive['manifest']['warnings'][0]['message']
              and commit(admin, inactive).status_code == 409, inactive['manifest'])
        r = upload(admin, workbook([row('QA9107', Class='GL')])); nonprop = r.json(); keys.append(ImportBatch.objects.get(pk=nonprop['id']).storage_key)
        check('a non-Property row with the Allianz Facility is a blocking warning', not nonprop['manifest']['errors']
              and any('Allianz Facility payment rule applies to Property only' in w['message'] for w in nonprop['manifest']['warnings']), nonprop['manifest'])
        r = upload(admin, workbook([row('QA9103', **{' Cedant Receipt No': 'CR', 'Receive Date': 'Claim'})])); nodate = r.json(); keys.append(ImportBatch.objects.get(pk=nodate['id']).storage_key)
        check('a settled premium side needs its Receive Date', 'Receive Date is required' in nodate['manifest']['errors'][0]['message'], nodate['manifest'])

        r = upload(admin, good); b = r.json(); m = b['manifest']; keys.append(ImportBatch.objects.get(pk=b['id']).storage_key)
        check('preview counts rows, classes and settlement', r.status_code == 201 and m['eligible'] == 8 and m['classes'] == {'PD': 7, 'GL': 1}
              and m['settlement'] == {'fully': 3, 'open': 5} and not m['errors'] and not m['warnings'], m)
        check('owner exclusion F13333 is listed and skipped', [x['serial'] for x in m['excluded']] == ['F13333'])
        check('owner correction F2898 is listed', m['corrections'][0]['serial'] == 'F2898' and m['corrections'][0]['changes']['Fac / Claim']['after'] == 'Fac')
        check('preview writes no transactions', not LegacyTransaction.objects.exists() and LegacyAudit.objects.filter(action='import_preview').count() == 8)
        check('a stale SHA256 is refused', commit(admin, b, 'f' * 64).status_code == 409)
        check('non-admin cannot commit', commit(fin, b).status_code == 403)
        r = commit(admin, b); done = r.json()
        check('admin commits the reviewed preview', r.status_code == 200 and done['status'] == 'imported' and done['manifest']['imported'] == 8, r.content[:400])
        check('a committed batch cannot be committed again', commit(admin, b).status_code == 409)
        t = {x.number: x for x in LegacyTransaction.objects.filter(batch_id=b['id'])}
        check('fully settled rows stay historical; open rows are trackable',
              {k for k, v in t.items() if v.historical} == {'QA9001', 'QA9004', 'F2898'} and {k for k, v in t.items() if not v.historical} == {'QA9002', 'QA9003', 'QA9005', 'QA9006', 'QA9007'})
        check('correction applied, original Register value kept', t['F2898'].data['kind'] == 'premium' and t['F2898'].data['newRenew'] == 'New'
              and t['F2898'].original.get('Fac / Claim') is None)
        check('rates from the Register formula (12.5% / 1%) are stored', t['QA9007'].data['commissionRate'] == 12.5 and t['QA9007'].data['taxRate'] == 1
              and t['QA9007'].data['rateSource'] == {'commissionRate': 'formula', 'taxRate': 'formula'}, t['QA9007'].data.get('rateSource'))
        check('rates from typed amounts (15% / 1%) are stored', t['QA9001'].data['commissionRate'] == 15 and t['QA9001'].data['taxRate'] == 1
              and t['QA9001'].data['rateSource'] == {'commissionRate': 'amount', 'taxRate': 'amount'})
        check('claims carry no premium rates', 'commissionRate' not in t['QA9004'].data)
        check('PD row stored as MDM PF Property with its Register code', t['QA9001'].data['classOfBusiness'] == 'Property' and t['QA9001'].data['classCode'] == 'PD')
        check('GL row stored as CGL', t['QA9003'].data['classOfBusiness'] == 'Commercial General Liability' and t['QA9003'].data['classCode'] == 'GL')
        check('import audit lists every transaction', set(LegacyAudit.objects.get(entity=b['id'], action='batch_imported').after['transactions']) == {str(x.uid) for x in t.values()})

        acc = accounting_get(admin, '?view=list').json()
        legs = {x['txNo']: x for x in acc['transactionRows'] if x.get('origin') == 'legacy'}
        check('Accounting has every imported leg without warnings', len(legs) == 22 and not acc['warnings'], (len(legs), acc['warnings'][:2]))
        a = legs['QA9001-T1']
        check('settled side: receipt with Accounting Dept. Ref. and Receive Date', a['settlement'] == 'settled' and a['paid'] == 8400
              and [(e['reference'], e['paymentDate'], e['entryKind']) for e in a['entries']] == [('CR-9001', '2026-05-10', 'legacy-import')])
        check('settled side: payment dated Pay Date', [(e['reference'], e['paymentDate']) for e in legs['QA9001-T2']['entries']] == [('RP-9001', '2026-05-20')])
        check('display date is the Effective Date', a['accountDisplayDate'] == '2026-03-01' and a['reconciliationRef'] == 'SOA-QA9001')
        name = 'Allianz Global Corporate & Specialty SE, Hong Kong Branch'
        check('Accounting drops (Facility) for historical and open rows alike; the Legacy record keeps it (2026-11-13)',
              legs['QA9001-T2']['partyName'] == name and legs['QA9002-T2']['partyName'] == name and t['QA9001'].data['party'] == FAC and t['QA9001'].data['rule'] == 'allianz',
              (legs['QA9001-T2']['partyName'], legs['QA9002-T2']['partyName']))
        from legacy.ledger import settlement_name
        check('any name ending in (Facility) is shown without it in Accounting',
              settlement_name(LegacyTransaction(data={'party': 'QA Other Re Ltd. (Facility)'})) == 'QA Other Re Ltd.'
              and settlement_name(LegacyTransaction(data={'party': 'QA Plain Re Ltd.'})) == 'QA Plain Re Ltd.')
        c1, c2 = legs['QA9004-C1-T1'], legs['QA9004-C1-T2']
        check('claim settles on the last day of Closed Month; display date is DOL',
              [(e['reference'], e['paymentDate']) for e in c1['entries']] == [('RR-9004', '2026-07-31')]
              and [(e['reference'], e['paymentDate']) for e in c2['entries']] == [('CP-9004', '2026-07-31')] and c1['accountDisplayDate'] == '2026-04-15')
        h1, h2, h3 = legs['QA9002-T1'], legs['QA9002-T2'], legs['QA9002-T3']
        check('half-settled row: settled side is reconciled before import', h1['settlement'] == 'settled' and h1['financeReviewed']
              and h1['reviewNote'] == 'Settled before import.' and not h1['canRecord'])
        check('half-settled row: open side waits for Finance review', h2['settlement'] == 'open' and not h2['financeReviewed'] and h2['outstanding'] == 6400
              and h2['dueDate'] and h3['settlement'] == 'open')
        q1, q2 = legs['QA9006-C1-T1'], legs['QA9006-C1-T2']
        check('open claim: due Issue Date of Claim + 15 days, reminder 7 days before (native claim rule)',
              q1['contractDueDate'] == '2026-10-28' and q1['dueDate'] == '2026-10-28' and q1['reminderDate'] == '2026-10-21'
              and q2['contractDueDate'] == '2026-10-28' and q1['settlement'] == 'open', (q1.get('contractDueDate'), q1.get('dueDate'), q1.get('reminderDate')))
        check('GL open row shows the Reinsurer Ref', legs['QA9003-T2']['reconciliationRef'] == 'RREF-9003')

        # Native Finance workflow on the open side, then T3 settles; imported receipts cannot be reversed.
        def fpost(body, want):
            r = fin.post('/api/accounting', json.dumps(body), content_type='application/json')
            check('Finance ' + body['action'] + ' ' + str(want), r.status_code == want, r.content[:600]); return r.json()
        def mem(no):
            x = LegacyTransaction.objects.get(number=no.split('-')[0]); return dict(caseUid=str(x.uid), rowVersion=x.version, txNo=no)
        x = LegacyTransaction.objects.get(number='QA9002')
        imported_bid = next(e['batchId'] for e in x.financial['paymentEntries'] if e.get('entryKind') == 'legacy-import')
        fpost(dict(action='reverse_batch_payment', batchId=imported_bid, paymentDate='2026-11-11', note='QA',
                   cases=[dict(caseUid=str(x.uid), rowVersion=x.version)]), 409)
        bat = next(x for x in accounting_get(admin, '?view=list').json()['cashBatches'] if x['batchId'] == imported_bid)
        check('settled-before-import registration is flagged and not reversible', bat.get('importedSettlement') and not bat['canReverse'] and bat['reference'] == 'CR-9002')
        check('settled-before-import receipt still in place', LegacyTransaction.objects.get(number='QA9002').financial['paymentEntries'] == x.financial['paymentEntries'])
        fpost(dict(action='record_transaction_payments', paymentDate='2026-11-11', reference='QA', amount=-6400,
                   allocations=[dict(**mem('QA9002-T2'), cashAmount=6400, offsetAmount=0)]), 409)
        fpost(dict(action='review_accounts', date='2026-11-11', members=[mem('QA9002-T2')]), 200)
        fpost(dict(action='record_transaction_payments', paymentDate='2026-11-11', reference='QA-PAY', amount=-6400,
                   allocations=[dict(**mem('QA9002-T2'), cashAmount=6400, offsetAmount=0)]), 200)
        legs = {x['txNo']: x for x in accounting_get(admin, '?view=list').json()['transactionRows'] if x.get('origin') == 'legacy'}
        check('open side settles through Finance and T3 follows', legs['QA9002-T2']['settlement'] == 'settled' and legs['QA9002-T3']['settlement'] == 'settled')
        hist = LegacyTransaction.objects.get(number='QA9001')
        fpost(dict(action='review_accounts', date='2026-11-11', members=[mem('QA9001-T1')]), 403)

        from legacy.ledger import payload_for
        for kind in ('endorsement', 'claim'):
            r = clients['sales'].post('/api/legacy', json.dumps(dict(referenceTransaction=str(t['QA9003'].uid), kind=kind)), content_type='application/json')
            new = LegacyTransaction.objects.get(pk=r.json()['uid']) if r.status_code == 201 else None
            check('new ' + kind + ' from a GL import keeps GL (CGL) in data and Accounting', new and new.data.get('classCode') == 'GL'
                  and new.data.get('classOfBusiness') == 'Commercial General Liability' and payload_for(new)['classCode'] == 'GL', r.content[:300])
            if new:
                r = clients['sales'].patch('/api/legacy', json.dumps(dict(id=str(new.uid), version=new.version, action='save', data={'remark': 'QA'})), content_type='application/json')
                check('saving the ' + kind + ' draft keeps GL', r.status_code == 200 and LegacyTransaction.objects.get(pk=new.uid).data.get('classCode') == 'GL', r.content[:300])
        r = clients['sales'].post('/api/legacy', json.dumps(dict(referenceTransaction=str(t['QA9007'].uid), kind='endorsement')), content_type='application/json')
        new = LegacyTransaction.objects.get(pk=r.json()['uid'])
        check('new endorsement from a PD import stays PD and pre-fills R/I Comm. % and Tax %', r.status_code == 201 and new.data.get('classCode') == 'PD'
              and new.data.get('commissionRate') == 12.5 and new.data.get('taxRate') == 1, r.content[:300])
        r = clients['sales'].post('/api/legacy', json.dumps(dict(referenceTransaction=str(t['QA9007'].uid), kind='claim')), content_type='application/json')
        check('new claim keeps zero rates', LegacyTransaction.objects.get(pk=r.json()['uid']).data.get('commissionRate') == 0)
        r = admin.patch('/api/legacy', json.dumps(dict(id=str(t['QA9003'].uid), version=t['QA9003'].version, action='retract')), content_type='application/json')
        check('imported rows cannot be returned to draft', r.status_code == 409, r.content[:200])
        # 2026-11-15 owner decision: imported premium/endorsement rows are Production by Revenue Month;
        # 2026-09 is before the start month (2026-11), so it is listed read-only as recognized Production.
        hist = admin.get('/api/production-report?month=2026-09').json()
        check('imported endorsement is listed as recognized Production in its historical Revenue Month',
              any(r.get('legacyTransactionId') == str(t['QA9005'].uid) for r in hist['rows']) and hist['scope']['historicalMonth'] and hist['scope']['monthClosed'], hist['scope'])
        r = admin.post('/api/production-report', json.dumps(dict(action='generate', month='2026-09', sourceSignature=hist['sourceSignature'])), content_type='application/json')
        check('a historical month cannot be generated', r.status_code == 409 and r.json().get('error') == 'historical_month', r.content[:200])
        check('native Case, Production and reconciliation records unchanged (apart from QA review)', native()[:2] == before[:2])

        r = upload(admin, good); again = r.json(); keys.append(ImportBatch.objects.get(pk=again['id']).storage_key)
        check('re-uploading skips already imported serials', again['manifest']['eligible'] == 0 and len(again['manifest']['duplicates']) == 8)
        check('nothing to import cannot be committed', commit(admin, again).status_code == 409 and LegacyTransaction.objects.filter(batch_id=again['id']).count() == 0)
        # 2026-11-16: any MDM Class code imports; Production and Dashboard follow the stored class.
        mar = admin.get('/api/production-report?month=2026-03').json()
        pr = {x.get('legacyTransactionId'): x.get('classCode') for x in mar['rows'] if x.get('legacyTransactionId')}
        check('Production shows the GL import as GL and PD as PD', pr.get(str(t['QA9003'].uid)) == 'GL' and pr.get(str(t['QA9001'].uid)) == 'PD', pr)
        r = upload(admin, workbook([row('QA9106', Class='qe', Reinsurer=ORD)])); qe = r.json(); keys.append(ImportBatch.objects.get(pk=qe['id']).storage_key)
        check('another MDM Class code (lower case) previews without errors or warnings', not qe['manifest']['errors'] and not qe['manifest']['warnings'], qe['manifest'])
        check('it imports with the MDM Class name', commit(admin, qe).status_code == 200
              and (lambda d: d['classOfBusiness'] == 'QA Engineering' and d['classCode'] == 'QE')(LegacyTransaction.objects.get(number='QA9106').data))
        from legacy.dashboard import dashboard_inputs
        names = {x['className'] for p in dashboard_inputs()['policies'] for x in p['items']}
        check('Dashboard groups legacy premium by the stored Class name', {'Property', 'Commercial General Liability', 'QA Engineering'} <= names, names)
        # ================= 2026-11-17：不保留上傳記錄；清單依 Transaction No. 由大到小 =================
        from datetime import timedelta
        from django.test import TestCase
        from django.utils import timezone
        check('no upload list or download (GET is not offered)', admin.get('/api/legacy/imports').status_code == 405
              and admin.get('/api/legacy/imports?download=' + b['id']).status_code == 405)
        done_batch = ImportBatch.objects.get(pk=b['id'])
        check('an imported batch keeps only its counts: no file name, workbook or preview contents',
              done_batch.status == 'imported' and done_batch.filename == '' and done_batch.storage_key == ''
              and done_batch.manifest == {'imported': 8, 'historical': 3, 'open': 5}, (done_batch.filename, done_batch.storage_key, done_batch.manifest))
        check('imported transactions still know they were imported', all(x.batch_id == done_batch.pk for x in t.values()))
        with TestCase.captureOnCommitCallbacks(execute=True):
            p1 = upload(admin, workbook([row('QA9201', Reinsurer=ORD)])).json()
        k1 = ImportBatch.objects.get(pk=p1['id']).storage_key
        check('a preview stores its workbook until it is imported or discarded', p1['status'] == 'preview' and storage.exists(k1))
        with TestCase.captureOnCommitCallbacks(execute=True):
            p2 = upload(admin, workbook([row('QA9202', Reinsurer=ORD)])).json()
        x1 = ImportBatch.objects.get(pk=p1['id'])
        check("a new preview discards the admin's earlier preview (workbook deleted, contents cleared)",
              x1.status == 'withdrawn' and x1.manifest == {} and x1.filename == '' and x1.storage_key == '' and not storage.exists(k1))
        check('a discarded preview cannot be imported', commit(admin, p1).status_code == 409)
        k2 = ImportBatch.objects.get(pk=p2['id']).storage_key
        with TestCase.captureOnCommitCallbacks(execute=True):
            r = admin.post('/api/legacy/imports', json.dumps({'action': 'discard', 'id': p2['id']}), content_type='application/json')
        x2 = ImportBatch.objects.get(pk=p2['id'])
        check('Clear / close discards the preview', r.status_code == 200 and x2.status == 'withdrawn' and not storage.exists(k2)
              and LegacyAudit.objects.filter(entity=p2['id'], action='import_discarded').exists(), r.content[:200])
        check('only admins may discard', fin.post('/api/legacy/imports', json.dumps({'action': 'discard', 'id': p2['id']}), content_type='application/json').status_code == 403)
        with TestCase.captureOnCommitCallbacks(execute=True):
            p3 = upload(admin, workbook([row('QA9203', Reinsurer=ORD)])).json()
            p4 = upload(admin, workbook([row('QA9204', Reinsurer=ORD)])).json()
        ImportBatch.objects.filter(pk=p3['id']).update(created_by='personnel:999999', status='preview', created_at=timezone.now() - timedelta(days=2))
        ImportBatch.objects.filter(pk=p4['id']).update(created_by='personnel:999998', status='preview')
        keys.append(ImportBatch.objects.get(pk=p4['id']).storage_key)
        with TestCase.captureOnCommitCallbacks(execute=True):
            p5 = upload(admin, workbook([row('QA9205', Reinsurer=ORD)])).json()
        check("another admin's preview older than one day is discarded; a recent one is kept",
              ImportBatch.objects.get(pk=p3['id']).status == 'withdrawn' and ImportBatch.objects.get(pk=p4['id']).status == 'preview')
        with TestCase.captureOnCommitCallbacks(execute=True):
            r = commit(admin, p5)
        x5 = ImportBatch.objects.get(pk=p5['id'])
        check('the workbook is deleted after a successful import', r.status_code == 200 and x5.storage_key == '' and x5.filename == ''
              and not storage.exists(f"legacy-imports/{p5['id']}/original.xlsx"), r.content[:200])
        rows = admin.get('/api/legacy?size=100').json()['rows']
        nums = [x['number'] for x in rows]
        import re as _re
        grp = lambda n: 0 if not n else 1 if n.startswith('LTX-') else 2
        drafts = [x for x in rows if not x['number']]
        rest = [n for n in nums if n and not n.startswith('LTX-')]
        check('list order: drafts first, then LTX numbers, then Register serials largest first (numeric)',
              [grp(n) for n in nums] == sorted(grp(n) for n in nums) and len(drafts) >= 1
              and [n for n in nums if n and n.startswith('LTX-')] == sorted([n for n in nums if n and n.startswith('LTX-')], reverse=True)
              and [int(_re.search(r'[0-9]+', n).group()) for n in rest] == sorted((int(_re.search(r'[0-9]+', n).group()) for n in rest), reverse=True)
              and rest[-1] == 'F2898' and rest[0] == 'QA9205', nums)
        raise Rollback()
except Rollback:
    pass
for key in keys:
    try: storage.delete(key)
    except Exception: pass
print(f'{len(checks)}/{len(checks)} passed legacy web import checks; database changes rolled back')
