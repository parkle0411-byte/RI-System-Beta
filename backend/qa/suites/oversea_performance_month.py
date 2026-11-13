from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
from cases.draft import normalize_draft
from cases.oversea import issues, edit_error
from production.calc import installment_allocations
base = {'reinsuranceStructure':'OVERSEA','classOfBusiness':'Fine Art','classCode':'FA','currency':'USD','originalInsured':'A','originalInsuredCn':'B','policyFrom':'2026-01-01','policyTo':'2027-01-01','ae':'AE','reinsured':'Cedant','originalPremium':1000,'receiptPaymentDate':'2026-05-01','reinsurers':[{'name':'Broker','sharePct':100,'brokerageAmount':100}], 'performanceMonth':''}
def labels(p): return [x['field'] for x in issues(p, ready=True)]
assert 'performanceMonth' in labels(base)
p=deepcopy(base);p['performanceMonth']='2026-01'
n=normalize_draft(p);assert not n['errors'],n['errors'];assert n['value']['performanceMonth']=='2026-01'
assert installment_allocations(n['value'])[0]['performanceMonth']=='2026-01'
legacy=deepcopy(p);del legacy['performanceMonth'];assert installment_allocations(legacy)[0]['performanceMonth']=='2026-05'
assert 'performanceMonth' not in labels(legacy)
assert 'performanceMonth' in labels(base)
p.update(installmentEnabled=True,performanceInstallments=[{'id':'I1','ratio':50,'paymentBaseDate':'2026-05-01','performanceMonth':'2026-01'},{'id':'I2','ratio':50,'paymentBaseDate':'2026-08-29','performanceMonth':'2026-04'}])
n=normalize_draft(p);assert not n['errors'],n['errors'];n=n['value']
assert [r['performanceMonth'] for r in installment_allocations(n)]==['2026-01','2026-04']
assert [r['income'] for r in installment_allocations(n)]==[50,50]
missing=deepcopy(n);missing['performanceInstallments'][1]['performanceMonth']='';assert 'performanceInstallments.1.performanceMonth' in labels(missing)
legacy=deepcopy(n);legacy['performanceInstallments'][0].pop('performanceMonth');assert installment_allocations(legacy)[0]['performanceMonth']=='2026-05'
assert 'performanceInstallments.0.performanceMonth' not in labels(legacy)
old=deepcopy(n);new=deepcopy(n);new['performanceInstallments'][0]['performanceMonth']='2026-02';case=SimpleNamespace(status='posted',payload=old)
with patch('production.models.ProductionExclusion.objects') as exclusions, patch('production.models.ProductionReport.objects') as reports:
 exclusions.filter.return_value.exists.return_value=False; reports.filter.return_value.exists.return_value=False
 assert edit_error(case,new,{'reason':'correction'})==''
 assert 'reason' in edit_error(case,new,{})
 reports.filter.return_value.exists.return_value=True
 assert 'closed' in edit_error(case,new,{'reason':'correction'})
 old['confirmedProductionKeys']=['5206:I1:R0']; assert 'locked' in edit_error(case,new,{'reason':'correction'})
from cases.workflow import build_endorsement_payload
endorsement=build_endorsement_payload({**base, 'performanceMonth':'2026-01'}, 'TW2601', 0)
assert endorsement['performanceMonth']==''
print('Oversea performance month checks passed')
