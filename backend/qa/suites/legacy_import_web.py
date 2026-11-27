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
        if isinstance(value, tuple):  # (formula, cached value[, 'e' for an error result])
            kind = ' t="e"' if value[2:] == ('e',) else ''
            return f'<c r="{ref}"{kind}><f>{escape(value[0])}</f><v>{escape(str(value[1]))}</v></c>'
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
        # 2026-11-17: claims carry no brokerage, so a claim with a Sub AE is not split (no 40/60 or 70/30 warning).
        cl = dict(**{'Fac / Claim': 'Claim', 'Claim': '1237.76', 'Our Share Premium': '0', 'R/I Comm.': '0', 'Tax': '0',
              'Bkg.\n(Original Currency)': '0', 'Bkg. (in TWD)': '0', 'Re Dept. Bkg.\n(in TWD)': ('ROUND(AJ2*AQ2,0)*0.4', '0'), 'Bkg.(%)': '0',
              'Net Premium from Cedant': '-1237.76', 'Net Premium to Reinsurer': '-1237.76', 'Revenue Month': 'N/A', 'Receive Date': 'Claim',
              'Pay Date': 'Claim', 'DOL': D('2026-04-15'), 'Issue Date of Claim': D('2026-10-13'), 'Currency': 'USD', 'Exchange Rate': '30',
              'Sub AE': 'QA Sub AE'})
        r = upload(admin, workbook([row('QA9109', Reinsurer=ORD, **cl)])); sc = r.json(); keys.append(ImportBatch.objects.get(pk=sc['id']).storage_key)
        check('a USD claim with a Sub AE and no brokerage previews without errors or warnings', not sc['manifest']['errors'] and not sc['manifest']['warnings'], sc['manifest'])
        check('it imports unsplit (100) and keeps the Sub AE name', commit(admin, sc).status_code == 200
              and (lambda d: d['aePct'] == 100 and d['subAe'] == 'QA Sub AE' and d['kind'] == 'claim')(LegacyTransaction.objects.get(number='QA9109').data))
        r = upload(admin, workbook([row('QA9110', Reinsurer=ORD, **{'Sub AE': 'QA Sub AE', 'Re Dept. Bkg.\n(in TWD)': '1000'})])); sp = r.json(); keys.append(ImportBatch.objects.get(pk=sp['id']).storage_key)
        check('a premium row with a 50/50 Sub AE split is still a blocking warning',
              [w['message'] for w in sp['manifest']['warnings']] == ['AE / Sub AE brokerage split is not 40/60 or 70/30.'] and commit(admin, sp).status_code == 409, sp['manifest'])
        r = upload(admin, workbook([row('QA9111', Reinsurer=ORD, **{'Sub AE': 'QA Sub AE', 'Re Dept. Bkg.\n(in TWD)': '1400'})])); s70 = r.json(); keys.append(ImportBatch.objects.get(pk=s70['id']).storage_key)
        check('a premium row with a 70/30 Sub AE split still imports as 70', not s70['manifest']['warnings'] and commit(admin, s70).status_code == 200
              and LegacyTransaction.objects.get(number='QA9111').data['aePct'] == 70, s70['manifest'])
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
        # ================= 2026-11-26：已結清理賠的 DOL 可留空；金額欄空白視為 0 =================
        def preview_rows(rows):
            r = upload(admin, workbook(rows)); data = r.json()
            keys.append(ImportBatch.objects.get(pk=data['id']).storage_key)
            return data
        paid = {'Fac / Claim': 'Claim', 'Claim': '600', 'Our Share Premium': '0', 'R/I Comm.': '0', 'Tax': '0', 'Bkg.(%)': '0',
                'Bkg.\n(Original Currency)': '0', 'Bkg. (in TWD)': '0', 'Re Dept. Bkg.\n(in TWD)': '0',
                'Net Premium from Cedant': '-600', 'Net Premium to Reinsurer': '-600', 'Revenue Month': 'N/A', 'Receive Date': 'Claim',
                'Pay Date': 'Claim', ' Cedant Payment No': 'CP', ' Reinsurer Receipt No': 'RR', 'Closed Month': D('2026-07-01')}
        dols = {'QA9301': 'December 2022', 'QA9302': 'June', 'QA9303': None, 'QA9304': 'June-22-AB', 'QA9305': D('2026-04-15')}
        p = preview_rows([row(s, Reinsurer=ORD, **{**paid, 'DOL': v}) for s, v in dols.items()])
        check('settled claims with a text or blank DOL preview without errors or warnings',
              p['manifest']['eligible'] == 5 and p['manifest']['settlement'] == {'fully': 5, 'open': 0}
              and not p['manifest']['errors'] and not p['manifest']['warnings'], p['manifest'])
        r = commit(admin, p)
        got = {x.number: x for x in LegacyTransaction.objects.filter(number__in=dols)}
        check('they import with an empty loss date; a real date is kept', r.status_code == 200
              and [got[s].data['lossDate'] for s in dols] == ['', '', '', '', '2026-04-15'],
              (r.content[:300], [x.data.get('lossDate') for x in got.values()]))
        check('the Register DOL text stays in the original Excel data', got['QA9301'].original.get('DOL') == 'December 2022'
              and got['QA9302'].original.get('DOL') == 'June' and 'DOL' not in got['QA9303'].original)
        shown = {x['txNo']: x for x in accounting_get(admin, '?view=list').json()['transactionRows'] if x.get('txNo', '').startswith('QA93')}
        check('Accounting lists them as settled with no display date', len(shown) == 10
              and all(x['settlement'] == 'settled' for x in shown.values())
              and shown['QA9301-C1-T1']['accountDisplayDate'] == '' and shown['QA9305-C1-T1']['accountDisplayDate'] == '2026-04-15',
              (len(shown), shown.get('QA9301-C1-T1', {}).get('accountDisplayDate')))
        unpaid = {**paid, ' Cedant Payment No': None, ' Reinsurer Receipt No': None, 'Issue Date of Claim': D('2026-10-13')}
        p = preview_rows([row('QA9306', Reinsurer=ORD, **{**unpaid, 'DOL': 'December 2022'}),
                          row('QA9307', Reinsurer=ORD, **{**paid, ' Reinsurer Receipt No': None, 'DOL': None, 'Issue Date of Claim': D('2026-10-13')})])
        check('open or half-settled claims without a real DOL are still blocking warnings',
              [(w['serial'], w['message']) for w in p['manifest']['warnings']] == [('QA9306', 'Claim without DOL.'), ('QA9307', 'Claim without DOL.')]
              and commit(admin, p).status_code == 409, p['manifest'])
        zero = {k: None for k in ('100%Premium', 'Our Share Premium', 'R/I Comm.', 'Claim', 'Tax', 'Bkg.\n(Original Currency)',
                                  'Bkg. (in TWD)', 'Re Dept. Bkg.\n(in TWD)', 'Net Premium from Cedant', 'Net Premium to Reinsurer')}
        p = preview_rows([row('QA9311', Reinsurer=ORD, **{'100%Premium': None, 'Tax': None, 'Claim': '   '}),
                          row('QA9312', Reinsurer=ORD, **{**zero, 'Endorsement No.': 'E-0', 'Bkg.(%)': None}),
                          row('QA9313', Reinsurer=ORD, **{**paid, **{k: None for k in zero if paid.get(k) == '0'}, '100%Premium': None, 'DOL': None})])
        check('blank amount cells preview without errors or warnings', p['manifest']['eligible'] == 3
              and not p['manifest']['errors'] and not p['manifest']['warnings'], p['manifest'])
        r = commit(admin, p)
        got = {x.number: x for x in LegacyTransaction.objects.filter(number__startswith='QA931')}
        a, z, c = got['QA9311'], got['QA9312'], got['QA9313']
        check('blank amounts are stored as 0', r.status_code == 200 and a.data['gross'] == 0 and a.data['amounts']['tax'] == 0
              and a.data['taxRate'] == 0 and a.data['amounts']['claim'] == 0 and a.data['amounts']['premium'] == 10000
              and all(z.data['amounts'][k] == 0 for k in ('premium', 'commission', 'tax', 'claim', 'brokerage', 'cedantNet', 'reinsurerNet'))
              and z.data['gross'] == 0 and z.fx_snapshot['incomeTwd'] == 0 and z.historical
              and c.data['amounts']['claim'] == 600 and c.data['amounts']['premium'] == 0, (r.content[:300], a.data['amounts'], z.data['amounts']))
        check('the original Excel data keeps the blank cells', '100%Premium' not in a.original and 'Tax' not in a.original
              and a.original.get('Claim') == '   ' and 'Net Premium from Cedant' not in z.original)
        p = preview_rows([row('QA9314', Reinsurer=ORD, Share=None), row('QA9315', Reinsurer=ORD, **{'Exchange Rate': None}),
                          row('QA9316', Reinsurer=ORD, Tax='N/A')])
        check('Share and Exchange Rate stay required; non-blank text in an amount cell is still an error',
              [x['message'] for x in p['manifest']['errors']] == ['Share is required for premium and endorsement rows.',
               'Exchange Rate is required.', 'Tax must be a finite number.'], p['manifest']['errors'])
        full = list(HEAD)
        HEAD.remove('Net Premium from Cedant'); HEAD.remove('100%Premium')
        try: r = upload(admin, workbook([row('QA9317', Reinsurer=ORD)]))
        finally: HEAD[:] = full
        check('a workbook without an amount column is refused instead of importing zeros', r.status_code == 400
              and b'missing amount columns: 100%Premium, Net Premium from Cedant.' in r.content, (r.status_code, r.content[:300]))
        # ================= 2026-11-27：closed＝x 且收付編號只是「v-…」註記 → 擋住匯入 =================
        cr, rp = ' Cedant Receipt No', ' Reinsurer Payment No.'
        message = lambda column, ref: (f'closed is x but {column} is only a note ({ref}); clear it if not yet received or paid, '
                                       'or enter the receipt/payment number.')
        p = preview_rows([row('QA9401', Reinsurer=ORD, closed='x', **{cr: '202610210', rp: 'v-11/13'}),
                          row('QA9402', Reinsurer=ORD, closed=' X ', **{cr: 'V -11/', rp: 'v-11/'}),
                          row('QA9403', Reinsurer=ORD, **{**paid, 'closed': 'x', ' Cedant Payment No': 'v-3/2', 'DOL': D('2026-04-15')}),
                          row('QA9404', Reinsurer=ORD, closed='x', **{cr: 'v-11/25'})])
        check('closed = x with a v- note is a blocking warning naming the column, on premium and claim rows',
              [(w['serial'], w['message']) for w in p['manifest']['warnings']] == [
                  ('QA9401', message('Reinsurer Payment No.', 'v-11/13')), ('QA9402', message('Cedant Receipt No', 'V -11/')),
                  ('QA9402', message('Reinsurer Payment No.', 'v-11/')), ('QA9403', message('Cedant Payment No', 'v-3/2')),
                  ('QA9404', message('Cedant Receipt No', 'v-11/25'))] and not p['manifest']['errors'], p['manifest'])
        check('it blocks the import', commit(admin, p).status_code == 409
              and not LegacyTransaction.objects.filter(number__startswith='QA940').exists())
        ok = [row('QA9411', Reinsurer=ORD, closed='x', **{cr: '202611106'}),                         # open, real number
              row('QA9412', Reinsurer=ORD, **{cr: 'v-11/25', rp: 'v-11/18'}),                       # closed blank
              row('QA9413', Reinsurer=ORD, closed='v', **{cr: 'v-11/25'}),                           # closed
              row('QA9414', Reinsurer=ORD, closed='x', **{cr: 'CR-1', rp: 'waived premium'}),       # other text
              row('QA9415', Reinsurer=ORD, closed='x'),                                              # nothing entered
              row('QA9416', Reinsurer=ORD, closed='x', **{cr: 'Rev-1', rp: 'INV-v-2'})]              # not starting with v-
        p = preview_rows(ok)
        check('other rows keep importing: closed not x, real numbers, other text or no number',
              not p['manifest']['warnings'] and not p['manifest']['errors'] and p['manifest']['eligible'] == 6, p['manifest'])
        p = preview_rows([row('QA9421', Reinsurer=ORD, closed='x', **{cr: '202610210'})])
        r = commit(admin, p)
        x = LegacyTransaction.objects.filter(number='QA9421').first()
        check('clearing the note imports the row with that side open', r.status_code == 200 and x and not x.historical
              and x.data['importSettlement'] == {'cedant': '202610210', 'reinsurer': ''}, r.content[:300])
        # ================= 2026-11-27：匯率待定（Exchange Rate 尚未決定）的外幣列 =================
        from fxrates.models import FxRate
        from legacy.services import rate_for
        err = lambda formula: (formula, '#VALUE!', 'e')
        bkg, redept, twd = 'Bkg.\n(Original Currency)', 'Re Dept. Bkg.\n(in TWD)', 'Bkg. (in TWD)'
        plain = 'IF(Z2="TWD",AJ2,ROUND(AJ2*AQ2,0))'
        usd = {'Reinsurer': ORD, 'Currency': 'USD', 'Effective Date': D('2026-11-07'), 'Revenue Month': D('2026-11-30'),
               '100%Premium': '16748.86', 'Our Share Premium': '8374.43', 'R/I Comm.': '0', 'Tax': '0', bkg: '502.47',
               'Net Premium from Cedant': '8374.43', 'Net Premium to Reinsurer': '7871.96', 'Receive Date': D('2027-01-15'), 'Pay Date': D('2027-01-20')}
        tba = {**usd, 'Exchange Rate': 'TBA', twd: err(plain), redept: err(plain)}
        sub40 = {'Sub AE': 'QA Sub AE', redept: err(plain + '*0.4')}
        sub70 = {'Sub AE': 'QA Sub AE', redept: err('ROUND(' + plain + '*0.7,0)')}
        claim_tba = {**paid, 'Reinsurer': ORD, 'Currency': 'USD', 'Exchange Rate': 'TBA', twd: err(plain), redept: err(plain), 'DOL': D('2026-11-02')}
        p = preview_rows([row('QA9501', **tba), row('QA9502', **{**tba, **sub40}),
                          row('QA9503', **{**tba, **sub70, ' Cedant Receipt No': 'CR-9503', ' Reinsurer Payment No.': 'RP-9503'}),
                          row('QA9504', **claim_tba), row('QA9505', **{**usd, 'Exchange Rate': None, twd: None, redept: None}),
                          row('QA9506', **{**usd, 'Exchange Rate': '30', twd: '15074', redept: '15074'})])
        check('foreign rows without an exchange rate preview without errors or warnings', p['manifest']['eligible'] == 6
              and not p['manifest']['errors'] and not p['manifest']['warnings'], p['manifest'])
        r = commit(admin, p)
        n = {x.number: x for x in LegacyTransaction.objects.filter(number__startswith='QA950')}
        check('they import marked as awaiting FX with no TWD figures; the split comes from the formula',
              r.status_code == 200 and all(n[s].data.get('fxPending') is True and n[s].fx_snapshot == {} for s in ('QA9501', 'QA9502', 'QA9503', 'QA9504', 'QA9505'))
              and [n[s].data['aePct'] for s in ('QA9501', 'QA9502', 'QA9503', 'QA9504', 'QA9505')] == [100, 40, 70, 100, 100]
              and n['QA9503'].historical and n['QA9504'].historical and not n['QA9501'].historical, r.content[:400])
        check('the Register values, TBA and #VALUE! included, stay in the original Excel data',
              n['QA9501'].original.get('Exchange Rate') == 'TBA' and n['QA9501'].original.get('Bkg. (in TWD)') == '#VALUE!')
        check('a row with a rate keeps the Register TWD figures', 'fxPending' not in n['QA9506'].data and n['QA9506'].fx_snapshot['incomeTwd'] == 15074)
        legs = [x['txNo'] for x in accounting_get(admin, '?view=list').json()['transactionRows'] if x.get('txNo', '').startswith('QA9501-')]
        check('original-currency Accounting accounts exist without a rate', len(legs) == 3, legs)
        detail = lambda s: admin.get('/api/legacy?id=' + str(n[s].uid)).json()['performance']
        check('open and settled rows both show Awaiting FX', detail('QA9501').get('awaitingFx') is True and detail('QA9503').get('awaitingFx') is True
              and detail('QA9506').get('awaitingFx') is False and detail('QA9504') == {}, (detail('QA9501'), detail('QA9504')))
        nov = lambda: [x['incomeTwd'] for x in dashboard_inputs()['trend'] if x['month'] == '2026-11']
        check('Dashboard brokerage leaves them out until the rate exists', sorted(nov(), key=str) == [15074, None, None, None, None], nov())
        prod = lambda: admin.get('/api/production-report?month=2026-11').json()
        post = lambda **body: admin.post('/api/production-report', json.dumps(dict(month='2026-11', **body)), content_type='application/json')
        before_fx = prod()
        r = post(action='generate', sourceSignature=before_fx['sourceSignature'])
        check('Production lists the missing rate and cannot be generated', before_fx['summary']['missingRateCurrencies'] == ['USD'] and r.status_code == 400
              and r.json().get('error') == 'fx_rate_required', (before_fx.get('summary'), r.content[:200]))
        fx = FxRate.objects.create(year_month='2026-11', currency='USD', rate='32.14', created_by='qa', updated_by='qa')
        got = prod()
        people = lambda s: [(x['ae'], x['income'], x['premium']) for x in got['rows'] if x.get('legacyTransactionId') == str(n[s].uid)]
        check('once the month rate exists the system converts them (100%, 40/60, 70/30)', got['summary']['missingRateCurrencies'] == []
              and people('QA9501') == [('QA AE', 16149, 269154)] and [x[1] for x in people('QA9502')] == [6460, 9689]
              and [x[1] for x in people('QA9503')] == [11305, 4844] and [x[1] for x in people('QA9506')] == [15074]
              and people('QA9504') == [], [people(s) for s in n])
        check('Dashboard brokerage now includes them', None not in nov() and len(nov()) == 5, nov())
        r = post(action='generate', sourceSignature=got['sourceSignature'])
        report = ProductionReport.objects.filter(year_month='2026-11').order_by('-version').first()
        r2 = post(action='close', reportUid=str(report.report_uid), rowVersion=report.row_version, sourceSignature=got['sourceSignature'])
        check('Production November generates and closes', r.status_code == 201 and r2.status_code in (200, 201), (r.content[:200], r2.content[:200]))
        frozen = {x.number: x.fx_snapshot for x in LegacyTransaction.objects.filter(number__startswith='QA950')}
        check('closing freezes the rate on the rows imported without one, and leaves the others',
              [frozen[s].get('rate') for s in ('QA9501', 'QA9502', 'QA9503', 'QA9505')] == [32.14] * 4 and frozen['QA9504'] == {}
              and frozen['QA9506'] == n['QA9506'].fx_snapshot
              and LegacyAudit.objects.filter(action='production_fx_frozen', entity__in=[str(x.uid) for x in n.values()]).count() == 4, frozen)
        FxRate.objects.filter(pk=fx.pk).update(rate='99', row_version=2)
        fresh = LegacyTransaction.objects.get(pk=n['QA9503'].pk)
        check('a later rate change does not move the frozen figures', rate_for(fresh)['rate'] == 32.14 and rate_for(fresh)['incomeTwd'] == 16149)
        p = preview_rows([row('QA9511', **{'Reinsurer': ORD, 'Exchange Rate': 'TBA'}), row('QA9512', **{**usd, 'Exchange Rate': '32..1'}),
                          row('QA9513', **{**tba, 'Tax': err('U4*0.01')}), row('QA9514', **{**usd, 'Exchange Rate': '30', twd: err(plain), redept: err(plain)}),
                          row('QA9515', **{**tba, 'Exchange Rate': err('VLOOKUP(1,2,3)')})])
        got = {w['serial']: w['message'] for w in p['manifest']['errors']}
        check('still errors: TWD rows, mistyped rates, other formula errors, rows with a rate', p['manifest']['eligible'] == 0
              and got['QA9511'] == got['QA9512'] == 'Exchange Rate must be a finite number.'
              and all(got[s].startswith('Formula errors or formulas without cached results: ') for s in ('QA9513', 'QA9514', 'QA9515'))
              and ',' not in got['QA9513'], got)
        p = preview_rows([row('QA9521', **{**tba, 'Sub AE': 'QA Sub AE'}), row('QA9522', **{**tba, redept: err(plain + '*0.4')}),
                          row('QA9523', **{**tba, 'Revenue Month': 'N/A'}), row('QA9524', **{**tba, 'Sub AE': 'QA Sub AE', redept: err(plain + '*0.5')})])
        split = 'Exchange Rate is not set: the Re Dept. Bkg. (in TWD) formula must end with *0.4 or *0.7 so the AE / Sub AE split can be read.'
        check('warnings block: unreadable split, share without Sub AE, no Revenue Month', [(w['serial'], w['message']) for w in p['manifest']['warnings']] == [
              ('QA9521', split), ('QA9522', 'The Re Dept. Bkg. (in TWD) formula takes a share but there is no Sub AE.'),
              ('QA9523', 'Revenue Month is required while the Exchange Rate is not set.'), ('QA9524', split)]
              and commit(admin, p).status_code == 409, p['manifest'])
        raise Rollback()
except Rollback:
    pass
for key in keys:
    try: storage.delete(key)
    except Exception: pass
print(f'{len(checks)}/{len(checks)} passed legacy web import checks; database changes rolled back')
