"""Full importer, matching, rollback and independently injected remapping failure."""
import os
import copy
from uuid import uuid4
from unittest import mock
from django.db import transaction
from django.test import override_settings
from audit.models import AuditLog, EntitySnapshot
from masterdata.models import MasterRecord
from conversion.alpha_format import COLUMNS, export_model_row
from conversion.importer import Importer, ConversionError
from conversion.models import MigrationBatch
from conversion import integrity, remap

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
results=[]
def check(name,ok,detail=''):
    results.append(bool(ok));print(('PASS ' if ok else 'FAIL ')+name+(' '+str(detail) if not ok else ''),flush=True)
class Rollback(Exception): pass
tag=uuid4().hex[:8]
def export(label):
    tables={t:[] for t in COLUMNS}
    base=dict(code=None,display_order=0,is_active=True,payload={},row_version=1,created_by='qa',updated_by='qa',
        created_at='2026-01-01T00:00:00Z',updated_at='2026-01-01T00:00:00Z',deactivated_by=None,deactivated_at=None)
    # Reinsurer intentionally precedes its referenced Classes.
    tables['ri_master_records']=[dict(base,id=900002,entity_type='reinsurer',name='ZZ Clause Re '+tag+' '+label,
        payload={'fixedClauses':[dict(code='QA-SCOPE',title='Scoped clause',classIds=[900001,'900003']),
                                dict(code='QA-ALL',title='All classes clause')]}),
        dict(base,id=900001,entity_type='class',code='ZZC'+tag+label,name='ZZ Clause Class '+tag+' '+label),
        dict(base,id=900003,entity_type='class',code='ZZD'+tag+label,name='ZZ Clause Class Two '+tag+' '+label)]
    return {'source':{'system':'synthetic-clause-remap'},'tables':tables}
def imported_re(doc):
    return MasterRecord.objects.get(name=doc['tables']['ri_master_records'][0]['name'],entity_type='reinsurer')
try:
    with transaction.atomic(),override_settings(AUDIT_LOG_PAUSED=True):
        audit_before=AuditLog.objects.count();doc=export('fresh');imp=Importer(doc,apply=True);result=imp.run()
        re=imported_re(doc);clause=re.payload['fixedClauses'][0]
        check('full importer commits remapped forward Class scopes',clause['classIds']==[imp.maps.masters[900001],str(imp.maps.masters[900003])],clause)
        check('source IDs differ from VM IDs',imp.maps.masters[900001]!=900001 and imp.maps.masters[900003]!=900003)
        check('All classes scope remains absent',not 'classIds' in re.payload['fixedClauses'][1])
        check('original export is not mutated',doc['tables']['ri_master_records'][0]['payload']['fixedClauses'][0]['classIds']==[900001,'900003'])
        check('round trip restores source scope types and IDs',remap.remap_master(export_model_row('ri_master_records',re),imp.maps.inverse())['payload']==doc['tables']['ri_master_records'][0]['payload'])
        check('independent integrity accepts correct scope',not integrity.check(doc['tables'],False,export_model_row))
        check('import batch completed',MigrationBatch.objects.get(batch_uid=result['batchUid']).status=='completed')
        again=Importer(doc,apply=True);again_result=again.run()
        check('existing masters match after mapping source scope IDs',again_result['matched']['ri_master_records']==3 and again_result['created']['ri_master_records']==0,again_result)
        check('matching import keeps existing scope unchanged',imported_re(doc).payload==re.payload)

        changed=copy.deepcopy(doc);changed['tables']['ri_master_records'][0]['payload']['fixedClauses'][0]['title']='Actual content difference'
        batches=MigrationBatch.objects.count();before=re.payload
        try:Importer(changed,apply=True).run();error=None
        except ConversionError as exc:error=exc.code
        check('actual mapped payload difference still refuses existing-master import',error=='reference_conflict',error)
        check('refused mismatch changes no payload or batch',imported_re(doc).payload==before and MigrationBatch.objects.count()==batches)

        missing=copy.deepcopy(doc);missing['tables']['ri_master_records'][0]['payload']['fixedClauses'][0]['classIds']=[999997]
        try:Importer(missing,apply=True).run();error=None
        except remap.RemapError:error='missing_reference'
        check('unknown source Class ID aborts import',error=='missing_reference')
        check('unknown ID leaves existing records and batch unchanged',imported_re(doc).payload==before and MigrationBatch.objects.count()==batches)

        corrupt=copy.deepcopy(before);corrupt['fixedClauses'][0]['classIds']=[900001,'900003']
        MasterRecord.objects.filter(pk=re.pk).update(payload=corrupt)
        problems=integrity.check(doc['tables'],False,export_model_row)
        check('independent integrity catches unconverted Class IDs',any('fixedClauses' in x for x in problems),problems)
        corrupt['fixedClauses'][0]['classIds']=[imp.maps.masters[900003],str(imp.maps.masters[900001])]
        MasterRecord.objects.filter(pk=re.pk).update(payload=corrupt)
        problems=integrity.check(doc['tables'],False,export_model_row)
        check('independent integrity catches wrong existing Class targets',any('fixedClauses' in x for x in problems),problems)
        MasterRecord.objects.filter(pk=re.pk).update(payload=before)

        fresh=export('broken');count=MasterRecord.objects.count();batches=MigrationBatch.objects.count();snapshots=EntitySnapshot.objects.count()
        with mock.patch.object(remap,'remap_master',side_effect=lambda row,maps:copy.deepcopy(row)):
            try:Importer(fresh,apply=True).run();error=None
            except ConversionError as exc:error=exc
        check('independent check rejects deliberately broken forward and reverse remapping',error is not None and error.code=='reconciliation_failed'
            and any('fixedClauses' in p for p in error.problems),getattr(error,'problems',None))
        check('failed integrity rolls back masters batches and snapshots',MasterRecord.objects.count()==count and MigrationBatch.objects.count()==batches
            and EntitySnapshot.objects.count()==snapshots)

        bad_type=copy.deepcopy(doc);bad_type['tables']['ri_master_records'][0]['payload']['fixedClauses'][0]['classIds']=[900002]
        corrupt=copy.deepcopy(before);corrupt['fixedClauses'][0]['classIds']=[re.pk];MasterRecord.objects.filter(pk=re.pk).update(payload=corrupt)
        problems=integrity.check(bad_type['tables'],False,export_model_row)
        check('scope must reference a Class rather than a reinsurer master',any('source scope must reference a Class' in x for x in problems),problems)
        MasterRecord.objects.filter(pk=re.pk).update(payload=before)

        dry=export('dry');count=MasterRecord.objects.count();result=Importer(dry,apply=False).run()
        check('dry run verifies scopes and leaves new masters absent',result['mode']=='DRY-RUN' and MasterRecord.objects.count()==count,result)
        check('dry run keeps original source IDs',dry['tables']['ri_master_records'][0]['payload']['fixedClauses'][0]['classIds']==[900001,'900003'])
        check('Audit remains paused',AuditLog.objects.count()==audit_before)
        raise Rollback()
except Rollback:pass
print(f'{sum(results)}/{len(results)} passed; database changes rolled back',flush=True)
assert all(results),results
