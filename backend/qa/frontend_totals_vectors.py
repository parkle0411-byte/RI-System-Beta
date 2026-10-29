"""Reproducible current/historical monetary inputs plus explicit malformed data.

Legal numeric cases and invalid shapes are checked separately. Deliberately
invalid underwriting input strings remain covered by normalize_draft suites.
"""
import copy,json,random,sys
from cases.calc.totals import case_totals
from cases.accounting_policy import FACILITIES
count=int(sys.argv[1]) if len(sys.argv)>1 else 3000
rng=random.Random(20261027)
rows=[]
for i in range(count):
 currency=rng.choice(['TWD','USD'])
 shares=rng.choice([[100],[60,40],[33.33,33.33,33.34],[0,100],[12.3456,27.6544,60]])
 sign=-1 if i%7==0 else 1
 amount=lambda:sign*rng.randint(1,10000000)/(1 if currency=='TWD' else 100)
 name=rng.choice(['QA Ordinary RI',*FACILITIES])
 p=dict(reinsuranceStructure='QS',classOfBusiness='Property',classCode='PD',currency=currency,
  originalPremium=amount(),riCommPct=rng.choice([0,5,12.5,17.35]),taxPct=rng.choice([0,1,1.2345]),
  reinsurers=[dict(name=name if j==0 else 'QA Ordinary '+str(j),sharePct=share,premium=amount(),riCommPct=rng.choice([0,5,10,17.35]),taxPct=rng.choice([0,1])) for j,share in enumerate(shares)])
 if sign<0:p['parentTwRef']='QA-ROOT'
 if i%11==0:p.update(accountingLegacyMath=True,premiumRounding='legacy-cents')
 rows.append({'case':p,'totals':case_totals(p),'kind':'protected-history' if p.get('accountingLegacyMath') else 'current'})
malformed=[dict(reinsurers=v) for v in [{},'bad',True,1,[None],[5],[[]],[{'name':42}]]]
malformed += [dict(reinsurers=[dict(name='QA')],originalPremium=v) for v in [{},[],True,'NaN','Infinity']]
malformed += [dict(reinsurers=[dict(name='QA',sharePct=v)]) for v in [[],{},'１２３','12 34']]
for p in malformed:rows.append({'case':p,'totals':case_totals(p),'kind':'malformed'})
print(json.dumps(rows,allow_nan=False))
