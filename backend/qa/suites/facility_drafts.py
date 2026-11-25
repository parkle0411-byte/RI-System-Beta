import json
import base64
import copy
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.test import Client
from cases.models import Case, FacilityDeclaration
from personnel.models import Personnel

User = get_user_model()
checks = []

def check(name, result, detail=''):
    checks.append((name, bool(result), str(detail)[:300]))

def session(role, number):
    department = 'finance' if role in ('accounting', 'accounting_manager') else 'reinsurance'
    person = Personnel.objects.create(name='Facility Test ' + str(number), department=department,
              role_code=role, created_by='qa', updated_by='qa')
    user = User.objects.create_user(username='facility-test-' + str(number), password='Facility-Test-Password-1')
    person.auth_user_id = str(user.pk); person.account_status = 'active'; person.save()
    client = Client(enforce_csrf_checks=True, HTTP_HOST='localhost', raise_request_exception=False)
    client.get('/api/auth/csrf'); cache.clear()
    response = client.post('/api/auth/login', data=json.dumps({'username': user.username, 'password': 'Facility-Test-Password-1'}),
        content_type='application/json', HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
    assert response.status_code == 200, response.content
    return client

def call(client, method, url, data=None):
    client.get('/api/auth/csrf')
    kwargs = {'HTTP_X_CSRFTOKEN': client.cookies['csrftoken'].value}
    if data is not None: kwargs.update(data=json.dumps(data), content_type='application/json')
    return getattr(client, method)(url, **kwargs)

class Rollback(Exception): pass

try:
    with transaction.atomic():
        sales, finance, manager = session('sales', 1), session('accounting', 2), session('accounting_manager', 3)
        facility = {'facilityName': 'Travel Facility', 'facilityTypePrefix': 'Travel', 'classOfBusiness': 'Personal Accident',
                    'reinsured': 'Cedant', 'originalAssuredDescription': 'Various groups as declared by the Reinsured',
                    'currency': 'USD', 'policyFrom': '2026-07-01', 'policyTo': '2027-07-01',
                    'riCommPct': 20, 'taxPct': 0, 'ppwDays': 75,
                    'reinsurers': [{'name': 'A', 'sharePct': 50, 'deductionPct': 30, 'taxPct': 0, 'facilityReference': 'RA'},
                                   {'name': 'B', 'sharePct': 30, 'deductionPct': 25, 'taxPct': 0, 'facilityReference': 'RB'}]}
        blocked = call(finance, 'post', '/api/facility-placement', {'case': facility})
        check('finance cannot create Facility', blocked.status_code == 403, blocked.content)
        incomplete = call(sales, 'post', '/api/facility-placement', {'case': {**facility, 'originalAssuredDescription': ''}})
        check('incomplete Facility can be saved as Draft', incomplete.status_code == 201, incomplete.content)
        if incomplete.status_code == 201:
            incomplete_case = incomplete.json()['case']
            not_ready = call(sales, 'post', '/api/facility-announce', {'caseUid': incomplete_case['caseUid'],
                             'rowVersion': incomplete_case['rowVersion'], 'confirmed': True})
            check('Original Insured is required to Announce', not_ready.status_code == 400 and
                  'Original Insured' in not_ready.json().get('message', ''), not_ready.content)
            missing_tax = copy.deepcopy(facility); missing_tax['reinsurers'][1]['taxPct'] = ''
            saved_tax = call(sales, 'put', '/api/facility-placement', {'caseUid': incomplete_case['caseUid'],
                             'rowVersion': incomplete_case['rowVersion'], 'case': missing_tax})
            check('Facility Draft may retain an unfilled Reinsurer Tax', saved_tax.status_code == 200, saved_tax.content)
            if saved_tax.status_code == 200:
                not_ready = call(sales, 'post', '/api/facility-announce', {'caseUid': incomplete_case['caseUid'],
                                 'rowVersion': saved_tax.json()['case']['rowVersion'], 'confirmed': True})
                check('Reinsurer Tax is required to Announce', not_ready.status_code == 400 and
                      'tax percentage' in not_ready.json().get('message', ''), not_ready.content)
        invalid_class = call(sales, 'post', '/api/facility-placement', {'case': {**facility, 'classOfBusiness': 'Property'}})
        check('Facility rejects non-PA insurance type', invalid_class.status_code == 400, invalid_class.content)
        response = call(sales, 'post', '/api/facility-placement', {'case': facility})
        check('create Facility draft', response.status_code == 201, response.content)
        assert response.status_code == 201, response.content
        uid = response.json()['case']['caseUid']
        case = Case.objects.get(case_uid=uid)
        check('no insured or financial transactions', case.insured_master_id is None and not case.payload.get('transactions'))
        attachment = call(sales, 'post', '/api/case-documents', {'caseUid': uid, 'kind': 'facility_attachment',
            'filename': 'facility.pdf', 'base64': base64.b64encode(b'%PDF-1.4\nFacility terms\n').decode()})
        check('Facility attachment can be uploaded', attachment.status_code == 201, attachment.content)
        facility['ownerPersonnelId'] = case.owner_personnel_id
        facility['aePersonnelId'] = case.ae_personnel_id
        invalid_edit = call(sales, 'put', '/api/facility-placement', {'caseUid': uid, 'rowVersion': 1,
                            'case': {**facility, 'classOfBusiness': 'Marine Cargo'}})
        case.refresh_from_db()
        check('Facility rejects changing PA to another insurance type', invalid_edit.status_code == 400 and
              case.payload['classOfBusiness'] == 'Personal Accident', invalid_edit.content)
        listing = call(sales, 'get', '/api/cases').json()['cases']
        check('Account List contains Facility name', any(item['caseUid'] == uid and item['originalInsured'] == 'Travel Facility' for item in listing))
        facility['facilityName'] = 'Travel Facility revised'
        update = call(sales, 'put', '/api/facility-placement', {'caseUid': uid, 'rowVersion': 1, 'case': facility})
        check('edit Facility draft', update.status_code == 200 and update.json()['case']['rowVersion'] == 2, update.content)
        stale = call(sales, 'put', '/api/facility-placement', {'caseUid': uid, 'rowVersion': 1, 'case': facility})
        check('stale Facility edit rejected', stale.status_code == 409, stale.content)
        declaration = {'periodFrom': '2026-07-01', 'periodTo': '2026-09-30', 'statementNo': 'S1', 'premium': 100, 'claim': 30}
        response = call(sales, 'post', '/api/facility-declarations', {'facilityUid': uid, 'declaration': declaration})
        check('unannounced Facility rejects Declaration', response.status_code == 409, response.content)
        announced = call(sales, 'post', '/api/facility-announce', {'caseUid': uid, 'rowVersion': 2, 'confirmed': True})
        check('announce Facility without premium', announced.status_code == 200 and announced.json()['case']['status'] == 'posted', announced.content)
        assert announced.status_code == 200, announced.content
        renewal = call(sales, 'post', '/api/facility-renewal', {'caseUid': uid, 'rowVersion': 3})
        check('create Facility renewal', renewal.status_code == 201, renewal.content)
        if renewal.status_code == 201:
            renewed = Case.objects.get(case_uid=renewal.json()['case']['caseUid'])
            check('renewal retains references without documents', renewed.payload['reinsurers'][0]['facilityReference'] == 'RA' and not renewed.documents.exists())
            check('renewal period shifted', renewed.payload['policyFrom'] == '2027-07-01' and renewed.payload['policyTo'] == '2028-07-01')
            duplicate_renewal = call(sales, 'post', '/api/facility-renewal', {'caseUid': uid, 'rowVersion': 3})
            check('duplicate renewal blocked', duplicate_renewal.status_code == 409, duplicate_renewal.content)
        response = call(sales, 'post', '/api/facility-declarations', {'facilityUid': uid, 'declaration': declaration})
        check('create Declaration draft', response.status_code == 201, response.content)
        assert response.status_code == 201, response.content
        saved = response.json()['declaration']; declaration_uid = saved['declarationUid']
        check('PPW uses declaration end', saved['payload']['dueDate'] == '2026-12-14', saved)
        for start in ('2026-06-30', '2026-07-01'):
            case.refresh_from_db()
            changed_terms = copy.deepcopy(case.payload); changed_terms['policyFrom'] = start
            sync = call(sales, 'put', '/api/facility-placement', {'caseUid': uid, 'rowVersion': case.row_version, 'case': changed_terms})
            synced = FacilityDeclaration.objects.get(declaration_uid=declaration_uid)
            check('Facility start synchronizes first Draft Declaration ' + start,
                  sync.status_code == 200 and synced.period_from.isoformat() == start, sync.content)
        case.refresh_from_db()
        invalid_terms = copy.deepcopy(case.payload); invalid_terms['policyFrom'] = '2026-10-01'
        invalid_sync = call(sales, 'put', '/api/facility-placement', {'caseUid': uid, 'rowVersion': case.row_version, 'case': invalid_terms})
        case.refresh_from_db(); synced.refresh_from_db()
        check('invalid synchronized period leaves both dates unchanged', invalid_sync.status_code == 400 and
              case.payload['policyFrom'] == '2026-07-01' and synced.period_from.isoformat() == '2026-07-01', invalid_sync.content)
        draft_version = synced.row_version
        no_evidence = call(sales, 'post', '/api/facility-declaration-announce', {'facilityUid': uid,
            'declarationUid': declaration_uid, 'rowVersion': draft_version, 'confirmed': True})
        check('Declaration cannot Announce without evidence', no_evidence.status_code == 400 and no_evidence.json().get('error') == 'evidence_required', no_evidence.content)
        doc_body = {'facilityUid': uid, 'declarationUid': declaration_uid, 'filename': 'statement.pdf',
                    'base64': base64.b64encode(b'%PDF-1.4\nFacility statement\n').decode()}
        doc = call(sales, 'post', '/api/facility-declaration-documents', doc_body)
        check('upload declaration evidence', doc.status_code == 201, doc.content)
        denied = call(finance, 'get', '/api/facility-declaration-documents?facilityUid=' + uid + '&declarationUid=' + declaration_uid)
        check('declaration evidence follows document read permission', denied.status_code == 403, denied.content)
        if doc.status_code == 201:
            doc_id = doc.json()['file']['id']
            listing = call(sales, 'get', '/api/facility-declaration-documents?facilityUid=' + uid + '&declarationUid=' + declaration_uid)
            check('list declaration evidence', listing.status_code == 200 and len(listing.json()['files']) == 1, listing.content)
            download = call(sales, 'get', '/api/facility-declaration-documents?facilityUid=' + uid + '&declarationUid=' + declaration_uid + '&fileId=' + doc_id)
            check('download declaration evidence', download.status_code == 200 and b''.join(download.streaming_content).startswith(b'%PDF-'), download.status_code)
        overlap = call(sales, 'post', '/api/facility-declarations', {'facilityUid': uid,
            'declaration': {**declaration, 'periodFrom': '2026-09-30', 'periodTo': '2026-10-31', 'statementNo': 'S2'}})
        check('overlapping Draft blocked', overlap.status_code == 400, overlap.content)
        duplicate = call(sales, 'post', '/api/facility-declarations', {'facilityUid': uid,
            'declaration': {**declaration, 'periodFrom': '2026-10-01', 'periodTo': '2026-12-31', 'statementNo': 's1'}})
        check('statement number unique', duplicate.status_code == 400, duplicate.content)
        updated = call(sales, 'put', '/api/facility-declarations', {'facilityUid': uid, 'declarationUid': declaration_uid,
            'rowVersion': draft_version, 'declaration': {**declaration, 'claim': 0}})
        check('Declaration draft edit', updated.status_code == 200 and updated.json()['declaration']['rowVersion'] == draft_version + 1, updated.content)
        listing = call(sales, 'get', '/api/facility-declarations?facilityUid=' + uid)
        check('list only Facility declarations', listing.status_code == 200 and len(listing.json()['declarations']) == 1, listing.content)
        check('no Declaration accounting created', not Case.objects.get(pk=case.pk).payload.get('transactions') and FacilityDeclaration.objects.filter(facility_id=case.pk).count() == 1)
        announced_declaration = call(sales, 'post', '/api/facility-declaration-announce', {'facilityUid': uid,
            'declarationUid': declaration_uid, 'rowVersion': draft_version + 1, 'confirmed': True})
        check('announce Declaration', announced_declaration.status_code == 200, announced_declaration.content)
        if announced_declaration.status_code == 200:
            result = announced_declaration.json()['declaration']
            case.refresh_from_db()
            check('Declaration preserves six transaction legs', result['status'] == 'posted' and len(case.payload['transactions']) == 6)
            for start in ('2026-06-30', '2026-07-01'):
                case.refresh_from_db()
                changed_terms = copy.deepcopy(case.payload); changed_terms['policyFrom'] = start
                sync = call(sales, 'put', '/api/facility-placement', {'caseUid': uid, 'rowVersion': case.row_version, 'case': changed_terms})
                synced = FacilityDeclaration.objects.get(declaration_uid=declaration_uid)
                case.refresh_from_db()
                check('Facility start corrects open Declaration ' + start,
                      sync.status_code == 200 and synced.period_from.isoformat() == start and len(case.payload['transactions']) == 6, sync.content)
            result['rowVersion'] = synced.row_version
            correction = call(sales, 'put', '/api/facility-declarations', {'facilityUid': uid,
                'declarationUid': declaration_uid, 'rowVersion': result['rowVersion'], 'declaration': {**declaration, 'premium': 120, 'claim': 0}})
            check('open month correction updates Declaration', correction.status_code == 200, correction.content)
            if correction.status_code == 200:
                result = correction.json()['declaration']
                case.refresh_from_db()
                check('open correction replaces original transactions', len(case.payload['transactions']) == 6 and result['payload']['premium'] == '120')
            from fxrates.models import FxRate
            from production.views import load_month
            revenue_month = result['payload']['revenueMonth']
            FxRate.objects.get_or_create(year_month=revenue_month, currency='USD', defaults={'rate': 30, 'created_by': 'qa', 'updated_by': 'qa'})
            from cases.facility_production import dashboard_trend
            trend = dashboard_trend({case.pk}, [{'year_month': revenue_month, 'currency': 'USD', 'rate': 30}], revenue_month)
            check('Dashboard shows Declaration brokerage in Revenue Month',
                  sum(row['incomeTwd'] for row in trend if row['month'] == revenue_month) == 234, trend)
            production = load_month(revenue_month)['preview']
            facility_rows = [row for row in production['rows'] if row.get('facilityDeclarationUid') == declaration_uid]
            check('Declaration appears in Revenue Month production', len(facility_rows) == 2, facility_rows)
            generated = call(manager, 'post', '/api/production-report', {'action': 'generate', 'month': revenue_month,
                'sourceSignature': production['sourceSignature']})
            check('generate Revenue Month report', generated.status_code == 201, generated.content)
            if generated.status_code == 201:
                report = generated.json()['report']
                closed = call(manager, 'post', '/api/production-report', {'action': 'close', 'month': revenue_month,
                    'reportUid': report['reportUid'], 'rowVersion': report['rowVersion'], 'sourceSignature': production['sourceSignature']})
                check('close declaration Revenue Month', closed.status_code == 200, closed.content)
                declaration_row = FacilityDeclaration.objects.get(declaration_uid=declaration_uid)
                check('closing freezes Facility rows', len(declaration_row.payload.get('productionRecognition') or []) == 2)
                if closed.status_code == 200:
                    case.refresh_from_db()
                    changed_terms = copy.deepcopy(case.payload); changed_terms['policyFrom'] = '2026-06-30'
                    sync = call(sales, 'put', '/api/facility-placement', {'caseUid': uid, 'rowVersion': case.row_version, 'case': changed_terms})
                    declaration_row.refresh_from_db(); case.refresh_from_db()
                    relevant = [row for row in case.payload['transactions'] if row.get('declarationUid') == declaration_uid]
                    check('Facility start corrects closed Declaration with reversal and replacement',
                          sync.status_code == 200 and declaration_row.period_from.isoformat() == '2026-06-30' and
                          len(relevant) == 18 and sum(bool(row.get('isReversalEntry')) for row in relevant) == 6, sync.content)
                    declaration['periodFrom'] = '2026-06-30'
                    corrected = call(sales, 'put', '/api/facility-declarations', {'facilityUid': uid,
                        'declarationUid': declaration_uid, 'rowVersion': declaration_row.row_version,
                        'declaration': {**declaration, 'premium': 150, 'claim': 0}})
                    check('closed declaration correction succeeds', corrected.status_code == 200, corrected.content)
                    if corrected.status_code == 200:
                        changed = corrected.json()['declaration']
                        case.refresh_from_db()
                        relevant = [row for row in case.payload['transactions'] if row.get('declarationUid') == declaration_uid]
                        check('closed correction preserves old, reversal and replacement', len(relevant) == 18 and sum(bool(row.get('isReversalEntry')) for row in relevant) == 6)
                        target = changed['payload']['latestRevenueMonth']
                        FxRate.objects.get_or_create(year_month=target, currency='USD', defaults={'rate': 30, 'created_by': 'qa', 'updated_by': 'qa'})
                        correction_preview = load_month(target)['preview']
                        correction_rows = [row for row in correction_preview['rows'] if row.get('facilityDeclarationUid') == declaration_uid]
                        check('closed correction has one negative and one positive per reinsurer', len(correction_rows) == 4 and
                              sum(row.get('facilityCorrectionSide') == 'reversal' for row in correction_rows) == 2 and
                              sum(row.get('facilityCorrectionSide') == 'replacement' for row in correction_rows) == 2, correction_rows)
                        second_report = call(manager, 'post', '/api/production-report', {'action': 'generate', 'month': target,
                            'sourceSignature': correction_preview['sourceSignature']})
                        check('generate correction report', second_report.status_code == 201, second_report.content)
                        if second_report.status_code == 201:
                            report2 = second_report.json()['report']
                            second_close = call(manager, 'post', '/api/production-report', {'action': 'close', 'month': target,
                                'reportUid': report2['reportUid'], 'rowVersion': report2['rowVersion'], 'sourceSignature': correction_preview['sourceSignature']})
                            check('close correction report', second_close.status_code == 200, second_close.content)
                            if second_close.status_code == 200:
                                refreshed = FacilityDeclaration.objects.get(declaration_uid=declaration_uid)
                                check('correction close freezes replacement rows only', len(refreshed.payload.get('productionRecognition') or []) == 2 and
                                      all(row.get('facilityCorrectionSide') == 'replacement' for row in refreshed.payload['productionRecognition']))
                                second_correction = call(sales, 'put', '/api/facility-declarations', {'facilityUid': uid,
                                    'declarationUid': declaration_uid, 'rowVersion': refreshed.row_version,
                                    'declaration': {**declaration, 'premium': 160, 'claim': 0}})
                                check('second closed correction preserves history', second_correction.status_code == 200, second_correction.content)
            accounting = call(finance, 'get', '/api/accounting?view=list&legacy=open')
            if accounting.status_code == 200:
                account_body = accounting.json()
                found = [x for x in account_body.get('transactionRows', []) if x.get('caseUid') == uid]
                active = [x for x in found if not x.get('reversed') and not x.get('isReversalEntry')]
                check('Accounting displays active Declaration transactions and history', len(active) == 6 and len(found) >= 6, str(found))
            else:
                check('Accounting displays Declaration transactions', False, accounting.content)
            case.refresh_from_db()
            revised_terms = copy.deepcopy(case.payload)
            revised_terms['reinsurers'][0]['facilityReference'] = 'RA-NEW'
            changed_ref = call(sales, 'put', '/api/facility-placement', {'caseUid': uid,
                'rowVersion': case.row_version, 'case': revised_terms})
            check('announced Facility reference can be updated', changed_ref.status_code == 200, changed_ref.content)
            if changed_ref.status_code == 200:
                account_body = call(finance, 'get', '/api/accounting?view=list&legacy=open').json()
                active = [x for x in account_body.get('transactionRows', []) if x.get('caseUid') == uid and
                          x.get('legType') == 'Leg 2' and x.get('reinsurerIdx') == 0 and not x.get('reversed') and not x.get('isReversalEntry')]
                check('new SoA uses current reinsurer reference', len(active) == 1 and active[0].get('reconciliationRef') == 'RA-NEW', active)
                case.refresh_from_db()
                receive = next(row for row in case.payload['transactions'] if row.get('declarationUid') == declaration_uid and
                               row.get('legType') == 'Leg 1' and row.get('reinsurerIdx') == 0 and not row.get('reversed') and not row.get('isReversalEntry'))
                member = {'caseUid': uid, 'txNo': receive['txNo'], 'rowVersion': case.row_version}
                review = call(finance, 'post', '/api/accounting', {'action': 'review_accounts', 'date': '2026-11-20', 'reference': 'QA', 'members': [member]})
                check('Finance can review a netted Facility receipt', review.status_code == 200, review.content)
                if review.status_code == 200:
                    case.refresh_from_db(); member['rowVersion'] = case.row_version
                    paid = call(finance, 'post', '/api/accounting', {'action': 'record_transaction_payments', 'paymentDate': '2026-11-20',
                        'reference': 'QA', 'amount': receive['amount'], 'allocations': [{**member, 'cashAmount': receive['amount'], 'offsetAmount': 0}]})
                    check('Finance can record netted Facility receipt', paid.status_code == 200, paid.content)
                    if paid.status_code == 200:
                        case.refresh_from_db()
                        blocked_terms = copy.deepcopy(case.payload); blocked_terms['policyFrom'] = '2026-06-29'
                        blocked_sync = call(sales, 'put', '/api/facility-placement', {'caseUid': uid, 'rowVersion': case.row_version, 'case': blocked_terms})
                        case.refresh_from_db(); locked_decl = FacilityDeclaration.objects.get(declaration_uid=declaration_uid)
                        check('paid Declaration blocks synchronized start correction without changing dates', blocked_sync.status_code == 409 and
                              case.payload['policyFrom'] == '2026-06-30' and locked_decl.period_from.isoformat() == '2026-06-30', blocked_sync.content)
                        current_decl = FacilityDeclaration.objects.get(declaration_uid=declaration_uid)
                        unsafe_correction = call(sales, 'put', '/api/facility-declarations', {'facilityUid': uid,
                            'declarationUid': declaration_uid, 'rowVersion': current_decl.row_version,
                            'declaration': {**declaration, 'premium': 170, 'claim': 0}})
                        check('active Finance review or cash blocks correction until reversed', unsafe_correction.status_code == 409, unsafe_correction.content)
                        case.refresh_from_db()
                        second_receipt = next(row for row in case.payload['transactions'] if row.get('declarationUid') == declaration_uid and
                            row.get('legType') == 'Leg 1' and row.get('reinsurerIdx') == 1 and not row.get('reversed') and not row.get('isReversalEntry'))
                        second_member = {'caseUid': uid, 'txNo': second_receipt['txNo'], 'rowVersion': case.row_version}
                        second_review = call(finance, 'post', '/api/accounting', {'action': 'review_accounts', 'date': '2026-11-20', 'reference': 'QA', 'members': [second_member]})
                        check('Finance can review second reinsurer share', second_review.status_code == 200, second_review.content)
                        if second_review.status_code == 200:
                            case.refresh_from_db(); second_member['rowVersion'] = case.row_version
                            second_paid = call(finance, 'post', '/api/accounting', {'action': 'record_transaction_payments', 'paymentDate': '2026-11-20',
                                'reference': 'QA', 'amount': second_receipt['amount'], 'allocations': [{**second_member, 'cashAmount': second_receipt['amount'], 'offsetAmount': 0}]})
                            check('Finance can collect second reinsurer share', second_paid.status_code == 200, second_paid.content)
                            if second_paid.status_code == 200:
                                case.refresh_from_db()
                                payment = next(row for row in case.payload['transactions'] if row.get('declarationUid') == declaration_uid and
                                    row.get('legType') == 'Leg 2' and row.get('reinsurerIdx') == 0 and not row.get('reversed') and not row.get('isReversalEntry'))
                                payment_member = {'caseUid': uid, 'txNo': payment['txNo'], 'rowVersion': case.row_version}
                                pay_review = call(finance, 'post', '/api/accounting', {'action': 'review_accounts', 'date': '2026-11-20', 'reference': 'QA', 'members': [payment_member]})
                                check('Finance can review netted reinsurer payment', pay_review.status_code == 200, pay_review.content)
                                if pay_review.status_code == 200:
                                    case.refresh_from_db(); payment_member['rowVersion'] = case.row_version
                                    payment_result = call(finance, 'post', '/api/accounting', {'action': 'record_transaction_payments', 'paymentDate': '2026-11-20',
                                        'reference': 'QA', 'amount': -payment['amount'], 'allocations': [{**payment_member, 'cashAmount': payment['amount'], 'offsetAmount': 0}]})
                                    check('Finance can pay netted reinsurer balance', payment_result.status_code == 200, payment_result.content)
            claim_only = {'periodFrom': '2027-07-02', 'periodTo': '2027-09-30', 'statementNo': 'CLAIM-ONLY', 'premium': 0, 'claim': 100}
            claim_draft = call(sales, 'post', '/api/facility-declarations', {'facilityUid': uid, 'declaration': claim_only})
            check('post-expiry Claim-only Declaration can be drafted', claim_draft.status_code == 201, claim_draft.content)
            if claim_draft.status_code == 201:
                claim_uid = claim_draft.json()['declaration']['declarationUid']
                claim_evidence = call(sales, 'post', '/api/facility-declaration-documents', {**doc_body, 'declarationUid': claim_uid})
                check('Claim-only evidence can be uploaded', claim_evidence.status_code == 201, claim_evidence.content)
                claim_announced = call(sales, 'post', '/api/facility-declaration-announce', {'facilityUid': uid,
                    'declarationUid': claim_uid, 'rowVersion': 1, 'confirmed': True})
                check('Claim-only Declaration can be announced after close', claim_announced.status_code == 200, claim_announced.content)
                if claim_announced.status_code == 200:
                    case.refresh_from_db()
                    claim_txs = [row for row in case.payload['transactions'] if row.get('declarationUid') == claim_uid]
                    check('Claim-only nets reverse collection directions without brokerage', len(claim_txs) == 6 and
                          all(row['amount'] <= 0 for row in claim_txs if row['legType'] in ('Leg 1', 'Leg 2')) and
                          all(row['amount'] == 0 for row in claim_txs if row['legType'] == 'Leg 3'))
            again = call(sales, 'post', '/api/facility-declaration-announce', {'facilityUid': uid,
                'declarationUid': declaration_uid, 'rowVersion': 2, 'confirmed': True})
            check('Declaration cannot be announced twice', again.status_code == 409, again.content)
        raise Rollback()
except Rollback:
    pass

for name, ok, detail in checks:
    if not ok: print('FAIL', name, detail)
passed = sum(1 for _, ok, _ in checks if ok)
print(f'{passed}/{len(checks)} passed')
if passed != len(checks): raise AssertionError('Facility draft tests failed')
