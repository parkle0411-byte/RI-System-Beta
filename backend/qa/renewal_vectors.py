"""Deterministic full-period-average vectors; no database access or real data."""
import copy
import json
import random
from datetime import date, timedelta
from cases.endorsement_rules import add_months
from cases.renewal_premiums import seed_renewal_premiums, refresh_renewal_premiums
from cases.workflow import shift_year

rng=random.Random(20261028)
vectors=[]
for index in range(2000):
    start=date(rng.randrange(2020,2060),rng.randrange(1,13),rng.randrange(1,29))
    days=rng.randrange(1,(add_months(start,18)-start).days+1)
    end=start+timedelta(days=days)
    currency='TWD' if index%3==0 else 'USD'
    scale=1 if currency=='TWD' else 100
    total=rng.randrange(1,100000000)/scale
    root={'policyFrom':start.isoformat(),'policyTo':end.isoformat(),'originalPremium':total,
          'reinsurers':[{'name':'QA A','premium':total*.8},{'name':'QA B','premium':total*.7}]}
    p={'policyFrom':end.isoformat(),'policyTo':shift_year(end.isoformat()),'currency':currency,
       'reinsuranceStructure':'QS','classOfBusiness':'Commercial General Liability' if index%4==0 else 'Property',
       'reinsurers':copy.deepcopy(root['reinsurers'])}
    seed_renewal_premiums(p,root,[],root)
    stored=copy.deepcopy(p)
    renewal_start=end+timedelta(days=rng.randrange(-10,11))
    maximum=(add_months(renewal_start,18)-renewal_start).days
    p['policyFrom']=renewal_start.isoformat()
    p['policyTo']=(renewal_start+timedelta(days=rng.randrange(1,maximum+1))).isoformat()
    if index%19==0:p['policyTo']='unfinished'
    if index%5==0:
        p['originalPremium']=rng.randrange(1,100000)/scale
        p['renewalPremiumManual'].append('originalPremium')
    if index%7==0:
        p['reinsurers'][0]['premium']=rng.randrange(1,100000)/scale
        p['renewalPremiumManual'].append('reinsurers.0.premium')
    candidate=copy.deepcopy(p)
    refresh_renewal_premiums(p,stored,candidate)
    vectors.append({'case':candidate,'expected':[p['originalPremium'],*[row['premium'] for row in p['reinsurers']]]})
print(json.dumps(vectors,allow_nan=False,separators=(',',':')))
