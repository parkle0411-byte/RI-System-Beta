from rest_framework.response import Response
from rest_framework.views import APIView
from coordination.services import serialized,PRODUCTION_SOURCES
from masterdata.models import MasterRecord
from ri_system.authz import RIPermission,NoStoreMixin,actor_from,AuthError
from . import insured_master as im
from .views import visible_cases

def details(record):
    return {**im.information(record),'history':(record.payload or {}).get('history',[])}

class InsuredMasterView(NoStoreMixin,APIView):
    permission_classes=[RIPermission]
    # 2026-10-29 業主：Case Viewer 不能看 Insured Master；只開放可看全部案件的角色（cases.read.all）
    permission_map={'GET':'cases.read.all','POST':'cases.write'}
    def get(self,request):
        visible=visible_cases(request.ri_principal)
        identity=request.query_params.get('id')
        if identity:
            if not str(identity).isdigit():raise AuthError(400,'invalid_insured_id','A valid insured master is required.')
            record=MasterRecord.objects.filter(entity_type='insured',pk=identity).first()
            if not record:raise AuthError(404,'insured_not_found','Insured master was not found.')
            record=im.canonical(record)
            # Account-wide readers also see empty masters; restricted readers see their linked insureds only.
            from ri_system.authz import has_permission
            if not has_permission(request.ri_principal,'cases.read.all') and not visible.filter(insured_master=record).exists():
                raise AuthError(404,'insured_not_found','Insured master was not found.')
            qs=visible.filter(insured_master=record).order_by('-effective_date','-id')
            page=max(1,min(100000,int(request.query_params.get('page','1')))) if str(request.query_params.get('page','1')).isdigit() else 1
            cases=[dict(caseUid=str(c.case_uid),twRef=c.tw_ref,status=c.status,caseKind=c.case_kind,
                originalInsuredCn=(c.payload or {}).get('originalInsuredCn',''),originalInsured=(c.payload or {}).get('originalInsured',''),
                className=c.class_name_snapshot,policyFrom=c.effective_date,policyTo=c.expiration_date,
                renewedFromTwRef=(c.payload or {}).get('renewedFromTwRef',''),parentTwRef=(c.payload or {}).get('parentTwRef','')) for c in qs[(page-1)*100:page*100]]
            return Response(dict(ok=True,record=details(record),cases=cases,caseCount=qs.count(),page=page,pageSize=100))
        from ri_system.authz import has_permission
        records=MasterRecord.objects.filter(entity_type='insured',is_active=True).order_by('name','id')
        if not has_permission(request.ri_principal,'cases.read.all'):records=records.filter(pk__in=visible.values('insured_master_id'))
        search=str(request.query_params.get('search') or '').strip().casefold()[:240]
        values=[im.information(r) for r in records]
        if search:values=[r for r in values if any(search in s.casefold() for s in [r['name'],*r['aliases']])]
        page=max(1,min(100000,int(request.query_params.get('page','1')))) if str(request.query_params.get('page','1')).isdigit() else 1
        return Response(dict(ok=True,records=values[(page-1)*50:page*50],total=len(values),page=page,pageSize=50))
    def post(self,request):
        body=request.data if isinstance(request.data,dict) else {}
        name=str(body.get('name') or '').strip()
        if not name or len(name)>240:raise AuthError(400,'insured_name_required','Enter a Chinese insured name (up to 240 characters).')
        actor=actor_from(request.ri_principal)
        with serialized(PRODUCTION_SOURCES):
            if body.get('id') is None:
                record=im.find_or_create(name,actor)
            else:
                if isinstance(body.get('id'),bool) or not str(body.get('id')).isdigit():
                    raise AuthError(400,'invalid_insured_id','A valid insured master is required.')
                record=MasterRecord.objects.filter(entity_type='insured',pk=body.get('id')).first()
                if not record:raise AuthError(404,'insured_not_found','Insured master was not found.')
                record=im.canonical(record)
                if isinstance(body.get('rowVersion'),bool) or body.get('rowVersion')!=record.row_version:
                    raise AuthError(409,'insured_version_conflict','The insured master changed elsewhere. Reload before saving.')
                try:record=im.rename(record,name,actor,{**body,'insuredMasterVersion':body['rowVersion']})
                except im.MergeRequired as exc:return Response(exc.data,status=409)
            return Response(dict(ok=True,record=details(record)))
