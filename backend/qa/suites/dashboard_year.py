import os
from datetime import datetime
from zoneinfo import ZoneInfo
from dashboard.calc import build_dashboard
assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
now=datetime(2026,11,6,tzinfo=ZoneInfo('Asia/Taipei'))
rows=[{'id':1,'status':'draft','payload':{}}]
targets=[{'period_type':'annual','period_key':'2025','amount':1200},{'period_type':'monthly','period_key':'2025-12','amount':100}]
closed=[{'year_month':'2025-12','rows':[{'caseId':1,'income':123},{'caseId':999,'income':99999}]},{'year_month':'2024-12','rows':[{'caseId':1,'income':45}]}]
base=build_dashboard(rows,targets,[],now,closed_reports=closed)
hist=build_dashboard(rows,targets,[],now,closed_reports=closed,brokerage_year=2025)
assert hist['metrics']==base['metrics'] and hist['period']==base['period']
assert hist['brokerage']['labels']==[f'{m:02}' for m in range(1,13)]
assert hist['brokerage']['current'][-1]==123
assert hist['brokerage']['prior'][-1]==45
assert hist['brokerage']['currentStatus'][-1]=='closed'
assert hist['brokerage']['priorStatus'][-1]=='closed'
assert hist['brokerage']['target'][-1]==100 and hist['brokerage']['annualTarget']==1200
assert len(base['brokerage']['labels'])==11
assert base==build_dashboard(rows,targets,[],now,closed_reports=closed,brokerage_year=2026)
print('10/10 historical dashboard checks passed')
