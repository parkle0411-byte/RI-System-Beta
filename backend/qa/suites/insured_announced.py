"""Announcement-only identity registration and explicitly confirmed insured changes."""
from pathlib import Path
exec(Path('/app/qa/suites/case_workflow.py').read_text().split('try:\n    with transaction.atomic():')[0])
import os
from masterdata.models import MasterRecord
from cases import insured_master as im
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
results=[]
def total():return MasterRecord.objects.filter(entity_type='insured').count()
try:
 with transaction.atomic():
  sales=account(person('sales','reinsurance'),'insured-announce')
  pending=MasterRecord.objects.create(entity_type='insured',name='裕程實業/六翊企業',payload={'aliases':['裕程實業'],'history':[{'action':'created','name':'裕程實業'},{'action':'renamed','before':'裕程實業','after':'裕程實業/六翊企業'}]},created_by='qa',updated_by='qa')
  c=create(sales,originalInsuredCn='裕程實業');check('Draft neither creates nor links a master',total()==1 and c.insured_master_id is None)
  p=copy.deepcopy(c.payload);p['originalInsuredCn']='裕程實業/六翊企業'
  r=call(sales,'put','/api/cases',{'caseUid':str(c.case_uid),'rowVersion':c.row_version,'case':p});c.refresh_from_db()
  check('Draft membership edits do not rename or create masters',r.status_code==200 and total()==1 and c.insured_master_id is None and MasterRecord.objects.get(pk=pending.pk).row_version==1)
  summary=call(sales,'get','/api/insured-masters?summary=1').json();check('formal count excludes all pending masters',summary['formalTotal']==0 and summary['pendingTotal']==1)
  r=announce(sales,c);check('failed Announce does not register or activate',r.status_code==400 and not im.is_official(MasterRecord.objects.get(pk=pending.pk)))
  docs=full_docs(c);r=announce(sales,c,docs);c.refresh_from_db();pending.refresh_from_db()
  check('successful Announce reuses and activates the matching pending master',r.status_code==200 and c.insured_master_id==pending.pk and im.is_official(pending),(r.status_code,r.content[:200]))
  check('old history remains distinctly pre-Announce',all(h.get('beforeAnnounce') for h in pending.payload['history'][:-1]) and pending.payload['history'][-1]['action']=='created')
  check('unverified pre-Announce aliases are not presented as formal former names',im.information(pending)['aliases']==[])
  solo=create(sales,originalInsuredCn='裕程實業');r=announce(sales,solo,full_docs(solo));solo.refresh_from_db()
  check('invalid old single-name alias cannot absorb a different combination',r.status_code==200 and solo.insured_master_id!=pending.pk and total()==2)
  other=create(sales,originalInsuredCn='六翊企業/裕程實業');r=announce(sales,other,full_docs(other));other.refresh_from_db();check('reversed member order shares the formal master',r.status_code==200 and other.insured_master_id==pending.pk and total()==2)
  def save_name(case,name,**extra):
   case.refresh_from_db();p=copy.deepcopy(case.payload);p['originalInsuredCn']=name
   return call(sales,'put','/api/cases',{'caseUid':str(case.case_uid),'rowVersion':case.row_version,'case':p,**extra})
  before=(total(),copy.deepcopy(pending.payload),c.row_version)
  r=save_name(c,'裕程實業新名/六翊企業');check('Announced edit must request a choice before writing',r.status_code==409 and r.json()['error']=='insured_change_required' and total()==before[0] and MasterRecord.objects.get(pk=pending.pk).payload==before[1])
  token=r.json()['insuredChange'];r=save_name(c,'裕程實業新名/六翊企業',insuredChange=token,insuredChangeKind='correction');c.refresh_from_db();pending.refresh_from_db();other.refresh_from_db()
  check('confirmed correction renames the same master',r.status_code==200 and c.insured_master_id==pending.pk and pending.payload['history'][-1]['action']=='renamed',(r.status_code,r.content[:200]))
  check('correction preserves other policy snapshots',other.payload['originalInsuredCn']=='六翊企業/裕程實業')
  r=save_name(c,'裕程實業新名/第三公司');token=r.json()['insuredChange'];r=save_name(c,'裕程實業新名/第三公司',insuredChange=token,insuredChangeKind='combination');c.refresh_from_db();pending.refresh_from_db()
  check('unconfirmed Announced case creates a missing new combination after choice',r.status_code==200 and c.insured_master_id!=pending.pk and total()==3)
  check('combination change does not rename the old identity',pending.name=='裕程實業新名/六翊企業')
  target=MasterRecord.objects.create(entity_type='insured',name='更正甲/更正乙',payload={'aliases':[],'history':[{'action':'created','name':'更正甲/更正乙'}]},created_by='qa',updated_by='qa')
  r=save_name(other,target.name);change=r.json()['insuredChange']
  r=save_name(other,target.name,insuredChange=change,insuredChangeKind='correction');target.refresh_from_db()
  check('merge confirmation leaves pending activation rolled back',r.status_code==409 and r.json()['error']=='insured_merge_required' and not im.is_official(target))
  merge=r.json()['insuredMerge'];r=save_name(other,target.name,insuredChange=change,insuredChangeKind='correction',insuredMerge=merge);target.refresh_from_db()
  check('confirmed merge activates pending target atomically',r.status_code==200 and im.is_official(target),r.content[:200])
  p=copy.deepcopy(c.payload);p['confirmedProductionKeys']=['confirmed-part'];Case.objects.filter(pk=c.pk).update(payload=p);c.refresh_from_db();before=(c.row_version,copy.deepcopy(c.payload),total())
  for name in ['不同名稱','第三公司/裕程實業新名','']:
   r=save_name(c,name,insuredChangeKind='correction');c.refresh_from_db();check('any confirmed portion blocks all direct name edits '+repr(name),r.status_code==409 and r.json()['error']=='insured_confirmed_locked' and (c.row_version,c.payload,total())==before)
  workflow_total=total()
  c.status='closed';c.save();r=wf(sales,'create_endorsement',c);check('Confirmed source can create an endorsement',r.status_code==201,r.content[:150])
  e=Case.objects.get(case_uid=r.json()['case']['caseUid']);check('endorsement Draft has no master link and creates none',e.insured_master_id is None and total()==workflow_total)
  root_name=c.payload['originalInsuredCn']
  ep=copy.deepcopy(e.payload);ep.update(originalInsuredCn='批單更正/第三公司',endoEffectiveDate='2026-06-01',endoTypes=['Premium'],endoText='Correct insured name.',originalPremium=0)
  for row in ep['reinsurers']:row['premium']=0
  e.payload=ep;e.save();edocs=[doc(e,'offer'),doc(e,'signed',['ZZ Re A']),doc(e,'confirmation',['zz  re b'])]
  r=announce(sales,e,edocs);check('endorsement Announce asks for the name-change classification',r.status_code==409 and r.json().get('error')=='insured_change_required',r.content[:350])
  if r.status_code==409 and r.json().get('insuredChange'):
   r=announce(sales,e,edocs,insuredChange=r.json()['insuredChange'],insuredChangeKind='correction');e.refresh_from_db();c.refresh_from_db()
   check('endorsed correction updates the master only on successful Announce',r.status_code==200 and e.insured_master_id==c.insured_master_id and e.insured_master.name=='批單更正/第三公司',r.content[:350])
   check('Confirmed original retains its historical name',c.payload['originalInsuredCn']==root_name)
  r=call(sales,'post','/api/insured-masters',{'name':'直接新增'});check('direct master creation is forbidden',r.status_code==403 and total()==workflow_total)
  r=call(sales,'post','/api/insured-masters',{'id':pending.pk,'rowVersion':pending.row_version,'name':'直接更名'});check('direct master rename is forbidden',r.status_code==403)
  summary=call(sales,'get','/api/insured-masters?summary=1').json();check('global count reflects official combinations rather than Cases',summary['formalTotal']==3 and summary['pendingTotal']==0)
  r=call(sales,'get','/api/insured-masters?search=不存在');check('search does not change tab count',r.json()['total']==0 and r.json()['formalTotal']==3)
  raise Rollback()
except Rollback:pass
for name,ok,detail in results:
 if not ok:print('FAIL '+name+' '+str(detail))
print(f'{sum(ok for _,ok,_ in results)}/{len(results)} insured announcement checks passed; test changes rolled back',flush=True);assert all(ok for _,ok,_ in results)
