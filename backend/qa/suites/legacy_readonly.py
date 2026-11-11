"""Phase-one read-only API/SQL guards. Synthetic data in disposable MySQL only."""
import copy,json,os,uuid
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connections,connection,transaction,DatabaseError
from django.test import Client
from django.utils import timezone
from legacy.models import ImportBatch,LegacyTransaction,LegacyAudit
from legacy.importer import excluded_row
from personnel.models import Personnel
from cases.models import Case,FinanceReconciliationBatch
from production.models import ProductionReport

assert os.environ.get('RI_DISPOSABLE_QA')=='true'
checks=[]
def check(name,value,detail=''):
    assert value,(name,detail)
    checks.append(name);print('PASS '+name,flush=True)
def post(c,url,body):return c.post(url,json.dumps(body),content_type='application/json')
def denied(sql):
    try:
        with transaction.atomic():
            with connection.cursor() as c:c.execute(sql)
    except DatabaseError:return True
    return False

owner=copy.deepcopy(connections.databases['default'])
owner.update(USER='ri_app',PASSWORD=Path('/run/secrets/mysql_app_password').read_text().strip())
connections.databases['legacy_qa_owner']=owner
with transaction.atomic(using='legacy_qa_owner'):
    batch=ImportBatch.objects.using('legacy_qa_owner').create(filename='synthetic.xlsx',sha256='a'*64,
        storage_key='qa/synthetic.xlsx',status='imported',created_by='isolated-qa')
    t=LegacyTransaction.objects.using('legacy_qa_owner').create(number='QA-LEG-1',original_serial='QA-LEG-1',
        reference='QA-OLD-REF',currency='TWD',revenue_month='2020-01',status='confirmed',historical=True,batch=batch,
        first_confirmed_at=timezone.now(),data=dict(reference='QA-OLD-REF',currency='TWD',revenueMonth='2020-01',insured='Synthetic Old Insured',
            insuredCn='測試歷史被保險人',cedant='Synthetic Cedant',party='Synthetic Reinsurer',ae='Synthetic AE',
            statementNo='OLD-STATEMENT-1',gross=10000,share=100,rule='ordinary',kind='premium',
            effectiveDate='2020-01-01',expiryDate='2021-01-01',receiveReminder='2020-03-15',payReminder='2020-04-15',
            amounts=dict(premium=10000,commission=0,tax=0,brokerage=500,claim=0,cedantNet=10000,reinsurerNet=9500)),
        fx_snapshot=dict(rate=1,incomeTwd=500,premiumTwd=10000,people=[dict(name='Synthetic AE',income=500)]))
    LegacyAudit.objects.using('legacy_qa_owner').create(entity=str(t.uid),action='synthetic_import',actor_name='isolated-qa')

check('anonymous legacy access denied',Client(HTTP_HOST='localhost').get('/api/legacy').status_code==401)
check('F13333 remains excluded from every import',excluded_row({'row':2801,'values':{'流水號':'F13333'}})['serial']=='F13333')
check('excluded serial does not hide similar identifiers',excluded_row({'row':1,'values':{'流水號':'F133330'}}) is None)

class Rollback(Exception):pass
try:
    with transaction.atomic():
        before_cases=Case.objects.count();clients={}
        for role in ('admin','sales','accounting','accounting_manager','general_manager','president','legacy_supervisor','viewer'):
            user=get_user_model().objects.create_user(username='qa-legacy-'+role,password='Legacy-QA-9!')
            Personnel.objects.create(name='QA Legacy '+role,department='board_of_directors' if role in ('president','legacy_supervisor') else 'reinsurance',
                role_code=role,auth_user_id=str(user.pk),account_status='active',created_by='qa',updated_by='qa')
            c=Client(HTTP_HOST='localhost');c.force_login(user);clients[role]=c
            r=c.get('/api/legacy')
            check(role+' legacy read scope',r.status_code==(403 if role=='viewer' else 200),r.content[:200])
            if role!='viewer':
                detail=c.get('/api/legacy?id='+str(t.uid)).json()
                check(role+' has no transaction write permission',not any(detail['permissions'].values()))
                for method in ('patch','delete'):
                    r=getattr(c,method)('/api/legacy',json.dumps(dict(id=str(t.uid),version=t.version,action='confirm',data={'brokerage':9999})),content_type='application/json')
                    check(role+' cannot '+method+' a legacy transaction',r.status_code==403,r.content[:200])
                r=post(c,'/api/legacy/imports',{'action':'commit','id':str(batch.pk),'sha256':batch.sha256})
                # 2026-11-11: System Administrators import on the web; an imported batch cannot be committed again.
                check(role+(' cannot re-import an imported batch' if role=='admin' else ' cannot import through HTTP'),r.status_code==(409 if role=='admin' else 403),r.content[:200])
        c=clients['admin'];rows=c.get('/api/accounting?view=list').json()['transactionRows']
        old=[r for r in rows if r.get('origin')=='legacy']
        check('one old transaction renders three native-style legs',len(old)==3)
        check('historical rows already reconciled without fabricated review identity',all(r['financeReviewed'] and not r['reviewDate'] and not r['reviewedByName'] and not r['reviewBatchId'] for r in old))
        check('historical rows remain settled with no cash events',all(r['settlement']=='settled' and r['outstanding']==0 and not r['entries'] and not r['canRecord'] for r in old))
        check('historical display date is the Effective Date (same position as native rows)',all(r['accountDisplayDate']=='2020-01-01' for r in old))
        check('Statement No. remains the source statement',all(r['statementNo']=='OLD-STATEMENT-1' for r in old))
        check('no new native Finance review batch inferred',FinanceReconciliationBatch.objects.count()==0)
        check('history never creates native Cases or Production reports',Case.objects.count()==before_cases and ProductionReport.objects.count()==0)
        for action in ('review_accounts','record_transaction_payments','cancel_review_batch','reverse_batch_payment','record_claim_followup','complete_payment_terms'):
            r=post(c,'/api/accounting',dict(action=action,caseUid=str(t.uid),rowVersion=t.version,
                members=[dict(caseUid=str(t.uid),txNo='QA-LEG-1-T1',rowVersion=t.version)]))
            check('Accounting blocks legacy '+action,r.status_code==403,r.content[:200])
        r=post(c,'/api/accounting',dict(action='review_accounts',members=[
            dict(caseUid=str(uuid.uuid4()),txNo='native-pretend',rowVersion=1),
            dict(caseUid=str(t.uid),txNo='QA-LEG-1-T1',rowVersion=t.version)]))
        check('mixed native/legacy write rejected before partial work',r.status_code==403 and FinanceReconciliationBatch.objects.count()==0)
        for sql in ('DELETE FROM ri_legacy_transactions','DELETE FROM ri_legacy_import_batches',
                    'UPDATE ri_legacy_audit SET action=action','DELETE FROM ri_legacy_audit'):
            check('runtime SQL mutation denied: '+sql.split(' SET')[0],denied(sql))
        check('runtime may record web import batches (INSERT/UPDATE, still no DELETE)',not denied(
            "INSERT INTO ri_legacy_import_batches(id,filename,sha256,storage_key,status,manifest,created_by,created_at,withdrawal) VALUES('00000000000000000000000000000001','x','x','x','preview','{}','qa',NOW(),'{}')") and not denied('UPDATE ri_legacy_import_batches SET filename=filename'))
        unchanged=LegacyTransaction.objects.get(pk=t.pk)
        check('all rejected writes preserve the old record',unchanged.version==1 and unchanged.data==t.data and unchanged.financial=={})
        check('no historical Production preview rows',c.get('/api/production-report?month=2020-01').json()['rows']==[])
        raise Rollback()
except Rollback:pass
print(f'{len(checks)}/{len(checks)} passed')
