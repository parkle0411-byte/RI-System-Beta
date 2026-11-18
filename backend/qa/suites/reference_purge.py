"""Permanent deletion uses only disposable document storage."""
import os,tempfile,uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from django.test import override_settings
from rest_framework.test import APIRequestFactory
from ri_system.reference_views import SystemReferenceView,MANUALS,write_row
from cases import storage
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
f=APIRequestFactory();checks=[]
def check(name,condition):
 assert condition,name
 checks.append(name);print('PASS '+name,flush=True)
def call(method='get',body=None,query='',role='admin'):
 actor=SimpleNamespace(pk=0,name='Purge Test',role_code=role,must_change_password=False)
 request=getattr(f,method)('/api/system-reference'+query,body,format='json')
 with patch('ri_system.authz.load_principal',return_value=actor),patch('ri_system.authz.is_supervisor',return_value=False):
  return SystemReferenceView.as_view()(request)
def act(key,action,manual=False,role='admin'):
 return call('patch',{'action':action,('manual' if manual else 'fileId'):key},role=role)
def template(folder,filename):
 key=str(uuid.uuid4());write_row(key,{'id':key,'filename':filename,'uploaded_at':'2026-11-17T00:00:00Z','uploaded_by':'qa','byte_size':9,'content_type':'application/pdf','kind':'template'})
 storage.put(f'system-reference/{key}.bin',b'%PDF-1.4\n');return key
with tempfile.TemporaryDirectory() as folder,override_settings(CASE_DOCUMENT_ROOT=folder):
 a=template(folder,'A.pdf');b=template(folder,'B.pdf');guide=next(iter(MANUALS));guide_file=Path('/app/ri_system/reference_documents')/MANUALS[guide];before=guide_file.read_bytes()
 check('reject active template',act(a,'purge').status_code==409)
 check('reject active guide',act(guide,'purge',True).status_code==409)
 for role in ('sales','accounting','viewer','president'):
  check('role denied '+role,act(a,'purge',role=role).status_code==403)
 check('anonymous denied',SystemReferenceView.as_view()(f.patch('/api/system-reference',{'action':'purge','fileId':a},format='json')).status_code==401)
 check('move template to bin',call('delete',query='?fileId='+a).status_code==200)
 check('purge template',act(a,'purge').status_code==200)
 listing=call().data
 check('deleted template absent from lists',all(row['id']!=a for row in listing['files']+listing['trash']))
 check('template content and metadata removed',not storage.exists(f'system-reference/{a}.bin') and not storage.exists(f'system-reference/{a}.json'))
 check('cannot restore or download purged template',act(a,'restore').status_code==404 and call(query='?fileId='+a).status_code==404)
 check('other template untouched',storage.exists(f'system-reference/{b}.bin') and any(r['id']==b for r in listing['files']))
 check('manual moved to bin',call('delete',query='?manual='+guide).status_code==200)
 check('purge manual',act(guide,'purge',True).status_code==200)
 listing=call().data
 check('purged manual not resurrected',all(r['id']!=guide for r in listing['manuals']+listing['trash']) and all(r['id']!=guide for r in call().data['manuals']))
 check('manual cannot be downloaded or restored',call(query='?manual='+guide).status_code==404 and act(guide,'restore',True).status_code==404)
 check('packaged manual retained',guide_file.read_bytes()==before)
 check('guide tombstone retains no filename',b'filename' not in storage.path_for('system-reference/manual-'+guide+'.json').read_bytes())
 check('other manuals still listed',len(listing['manuals'])==len(MANUALS)-1)
 for failure_target in ('bin','json'):
  key=template(folder,f'Failed {failure_target}.pdf');call('delete',query='?fileId='+key)
  native=storage.delete
  def fail(path):
   if path.endswith('.'+failure_target):raise OSError('simulated storage error')
   return native(path)
  with patch('ri_system.reference_views.storage.delete',side_effect=fail):
   response=act(key,'purge')
  check(failure_target+' failure is reported',response.status_code==503)
  row=next(r for r in call().data['trash'] if r['id']==key)
  check(failure_target+' failure stays in bin for retry',bool(row.get('purging_at')))
  check(failure_target+' failure cannot restore or rename',act(key,'restore').status_code==409 and act(key,'rename').status_code==409)
  check(failure_target+' retry completes',act(key,'purge').status_code==200 and not storage.exists(f'system-reference/{key}.json') and not storage.exists(f'system-reference/{key}.bin'))
 key=template(folder,'Interrupted.pdf');call('delete',query='?fileId='+key)
 try:
  with patch('ri_system.reference_views.storage.delete',side_effect=SystemExit('simulated process death')):act(key,'purge')
 except SystemExit:pass
 check('interrupted purge cannot be restored',act(key,'restore').status_code==409)
 check('interrupted purge can be retried',act(key,'purge').status_code==200)
 check('invalid identifier rejected',act('../outside','purge').status_code==404)
print(f'{len(checks)}/{len(checks)} reference purge checks passed',flush=True)
