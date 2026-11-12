from cases.draft import normalize_draft
from cases.draft_input import normalize, validate
p={'classCode':'ST','classOfBusiness':'Stock Throughput','reinsuranceStructure':'QS','currency':'USD','typePrefix':'Stock Throughput','limitOfLiability':'USD 1m any one occurrence\nUSD 2m aggregate','conveyance':'Sea','voyage':'Worldwide','stpTurnoverMode':'combined','stpTurnover':[{'company':'','currency':'USD','amount':123},{'company':'','currency':'TWD','amount':456}],'stpHubs':[{'name':'A','address':'Road','currency':'USD','amount':500}]}
a=normalize_draft(p)
assert not a['errors'], a['errors']
assert a['value']['limitOfLiability']==p['limitOfLiability']
assert a['value']['stpHubs']==p['stpHubs']
r=normalize(p)
assert not r['errors'],r['errors']
assert r['value']['draftInput']['stpTurnover']==p['stpTurnover']
v, issues=validate(r['value'])
assert not issues, issues
assert v['stpTurnover']==p['stpTurnover']
assert v['limitOfLiability']==p['limitOfLiability']
print('STP draft round-trip smoke test passed')
from cases.draft import validate_announce_ready
p.update(ownerPersonnelId=1, ae='QA AE', originalInsured='Acme', originalInsuredCn='安可', reinsured='Cedant',
         newOrRenew='New', policyFrom='2026-01-01', policyTo='2027-01-01', interest='Stock',
         situations=[{'address':'Taipei','postcode':'100'}], originalPremium=1000, riCommPct=0, taxPct=1,
         paymentTermsDays=90, reinsurers=[{'name':'Ordinary Re','sharePct':20,'premium':1000,'riCommPct':10,'taxPct':0,'paymentTermsDays':90}],
         deductibles='USD 1,000', originalConditions='Condition A', reinsuredRetention='Waived',
         expressWarranties='None', conditionsPrecedent='None', subjectivities='None', lossAdvisedDate='2026-01-01',lossRecordYears=5)
a=normalize_draft(p)
assert not a['errors'], a['errors']
problems=validate_announce_ready(a['value'],allow_zero_loss_years=True,case_kind='original')
assert not problems, problems
print('STP announce readiness smoke test passed')
from cases.qs_documents import readiness_issues, scope
assert scope(a['value'],'cover')
assert not readiness_issues(a['value'],'cover','ae@example.test'), readiness_issues(a['value'],'cover','ae@example.test')
print('STP stored Cover Note readiness smoke test passed')
from cases.property_original import totals
ledger=totals(a['value'])
assert ledger['leg1']==198 and ledger['leg2']==180 and ledger['leg3']==18, ledger
print('STP T1/T2/T3 accounting smoke test passed')
