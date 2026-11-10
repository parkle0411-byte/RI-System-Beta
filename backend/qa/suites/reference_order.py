"""Shared ordering, conflict rejection, lifecycle and authorization in disposable storage."""
import os,tempfile,json,uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from django.test import override_settings
from rest_framework.test import APIRequestFactory
from ri_system.reference_views import SystemReferenceView,write_row
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
checks=[]
def check(label,condition):
 assert condition,label
 checks.append(label);print('PASS '+label,flush=True)
f=APIRequestFactory()
def call(method='get',body=None,query='',role='admin',name='Admin One'):
 principal=SimpleNamespace(pk=0,name=name,role_code=role,must_change_password=False)
 req=getattr(f,method)('/api/system-reference'+query,body,format='json')
 with patch('ri_system.authz.load_principal',return_value=principal),patch('ri_system.authz.is_supervisor',return_value=False):
  return SystemReferenceView.as_view()(req)
def ids(data,key):return [r['id'] for r in data[key]]
def save(data,key,order):return call('patch',dict(action='reorder',category=key,ids=order,orderVersion=data['orderVersions'][key]))
with tempfile.TemporaryDirectory() as folder,override_settings(CASE_DOCUMENT_ROOT=folder):
 first=call().data;original=ids(first,'manuals');wanted=list(reversed(original))
 check('manual order saves',save(first,'manuals',wanted).status_code==200)
 shared=call(name='Admin Two').data
 check('another admin sees saved order',ids(shared,'manuals')==wanted)
 check('template order unchanged',shared['files']==first['files'])
 check('stale session rejected',save(first,'manuals',original).status_code==409)
 check('duplicate IDs rejected',save(shared,'manuals',wanted+[wanted[0]]).status_code==400)
 check('missing IDs rejected',save(shared,'manuals',wanted[:-1]).status_code==409)
 check('unknown IDs rejected',save(shared,'manuals',wanted[:-1]+['missing']).status_code==409)
 for category in (None,{},'trash'):
  check('invalid category '+str(category),call('patch',dict(action='reorder',category=category,ids=[])).status_code==400)
 for bad in (None,{},[1],['a','a']):
  check('invalid ID list '+str(bad),call('patch',dict(action='reorder',category='manuals',ids=bad)).status_code==400)
 for role in ('sales','accounting','viewer','president'):
  check('non-admin cannot reorder '+role,call('patch',dict(action='reorder',category='manuals',ids=wanted),role=role).status_code==403)
 check('anonymous rejected',SystemReferenceView.as_view()(f.patch('/api/system-reference',dict(action='reorder',category='manuals',ids=wanted),format='json')).status_code==401)
 key=wanted[2]
 check('delete manual',call('delete',query='?manual='+key).status_code==200)
 deleted=call().data;changed=ids(deleted,'manuals');changed[0],changed[1]=changed[1],changed[0]
 check('reorder while manual in trash',save(deleted,'manuals',changed).status_code==200)
 check('restore manual',call('patch',dict(action='restore',manual=key)).status_code==200)
 restored=call().data;expected=changed[:2]+[key]+changed[2:]
 check('restored manual retains slot',ids(restored,'manuals')==expected)
 check('rename manual',call('patch',dict(action='rename',manual=key,name='Renamed guide')).status_code==200)
 check('rename preserves order',ids(call().data,'manuals')==expected)
 for n in range(3):
  key=str(uuid.uuid4());write_row(key,dict(id=key,filename=f'Template {n}.pdf',uploaded_at=f'2026-11-04T00:00:0{n}Z',content_type='application/pdf',byte_size=6))
 templates=call().data;wanted_files=list(reversed(ids(templates,'files')))
 check('template order saves',save(templates,'files',wanted_files).status_code==200)
 check('template order shared',ids(call(name='Admin Two').data,'files')==wanted_files)
 check('guide order independent',ids(call().data,'manuals')==expected)
 new=str(uuid.uuid4());write_row(new,dict(id=new,filename='New.pdf',uploaded_at='2026-11-04T00:00:09Z'))
 check('new template appended',ids(call().data,'files')==wanted_files+[new])
 check('concurrent upload rejects stale reorder',save(templates,'files',wanted_files).status_code==409)
 listing=call().data
 check('ordering metadata not listed as unreadable template',listing['unreadable']==0)
 before={str(p):p.read_bytes() for p in Path(folder).rglob('*.json')}
 check('invalid reorder does not write metadata',save(listing,'files',[]).status_code==409 and before=={str(p):p.read_bytes() for p in Path(folder).rglob('*.json')})
 order=Path(folder)/'system-reference/.orders/manuals.json';order.write_text('{broken')
 check('corrupt order fails visibly',call().status_code==503)
 check('corrupt order not overwritten',save(listing,'manuals',expected).status_code==503 and order.read_text()=='{broken')
print(f'{len(checks)}/{len(checks)} reference ordering checks passed',flush=True)
