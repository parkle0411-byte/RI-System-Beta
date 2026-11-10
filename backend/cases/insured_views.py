from rest_framework.response import Response
from rest_framework.views import APIView
from coordination.services import serialized,PRODUCTION_SOURCES
from masterdata.models import MasterRecord
from ri_system.authz import RIPermission,NoStoreMixin,actor_from,AuthError
from . import insured_master as im
from .views import visible_cases

def details(record, official=None):
    return {**im.information(record,official=official),'history':(record.payload or {}).get('history',[])}

class InsuredMasterView(NoStoreMixin,APIView):
    permission_classes=[RIPermission]
    # 2026-10-29 業主：Case Viewer 不能看 Insured Master；只開放可看全部案件的角色（cases.read.all）
    permission_map={'GET':'cases.read.all','POST':'cases.write'}
    def get(self,request):
        visible=visible_cases(request.ri_principal)
        identity=request.query_params.get('id')
        all_records=list(MasterRecord.objects.filter(entity_type='insured',is_active=True).order_by('name','id'))
        from .models import Case
        official_ids=set(Case.objects.filter(announced_at__isnull=False,insured_master_id__isnull=False).values_list('insured_master_id',flat=True))
        official_ids.update(r.pk for r in all_records if (r.payload or {}).get(im.OFFICIAL_KEY))
        official_ids.intersection_update(r.pk for r in all_records)
        formal_total=len(official_ids);pending_total=len(all_records)-formal_total
        if request.query_params.get('summary')=='1':
            return Response(dict(ok=True,formalTotal=formal_total,pendingTotal=pending_total))
        if identity:
            if not str(identity).isdigit():raise AuthError(400,'invalid_insured_id','A valid insured master is required.')
            record=MasterRecord.objects.filter(entity_type='insured',pk=identity).first()
            if not record:raise AuthError(404,'insured_not_found','Insured master was not found.')
            record=im.canonical(record)
            # Account-wide readers also see empty masters; restricted readers see their linked insureds only.
            from ri_system.authz import has_permission
            if not has_permission(request.ri_principal,'cases.read.all') and not visible.filter(insured_master=record).exists():
                raise AuthError(404,'insured_not_found','Insured master was not found.')
            qs=visible.filter(insured_master=record)
            if record.pk in official_ids:qs=qs.filter(announced_at__isnull=False)
            qs=qs.order_by('-effective_date','-id')
            page=max(1,min(100000,int(request.query_params.get('page','1')))) if str(request.query_params.get('page','1')).isdigit() else 1
            cases=[dict(caseUid=str(c.case_uid),twRef=c.tw_ref,status=c.status,caseKind=c.case_kind,
                originalInsuredCn=(c.payload or {}).get('originalInsuredCn',''),originalInsured=(c.payload or {}).get('originalInsured',''),
                className=c.class_name_snapshot,policyFrom=c.effective_date,policyTo=c.expiration_date,
                renewedFromTwRef=(c.payload or {}).get('renewedFromTwRef',''),parentTwRef=(c.payload or {}).get('parentTwRef','')) for c in qs[(page-1)*100:page*100]]
            return Response(dict(ok=True,record={**details(record,official=record.pk in official_ids),'registrationStatus':'formal' if record.pk in official_ids else 'pending'},cases=cases,caseCount=qs.count(),page=page,pageSize=100))
        from ri_system.authz import has_permission
        records=MasterRecord.objects.filter(entity_type='insured',is_active=True).order_by('name','id')
        if not has_permission(request.ri_principal,'cases.read.all'):records=records.filter(pk__in=visible.values('insured_master_id'))
        search=str(request.query_params.get('search') or '').strip().casefold()[:240]
        pending=request.query_params.get('scope')=='pending'
        values=[im.information(r,official=r.pk in official_ids) for r in records if (r.pk not in official_ids)==pending]
        if search:
            try:
                key = im.combination_key(search)
            except AuthError:
                key = None
            values = [r for r in values if any(search in s.casefold() or
                      (key is not None and im.combination_key(s) == key)
                      for s in [r['name'], *r['aliases']])]
        page=max(1,min(100000,int(request.query_params.get('page','1')))) if str(request.query_params.get('page','1')).isdigit() else 1
        return Response(dict(ok=True,records=values[(page-1)*50:page*50],total=len(values),formalTotal=formal_total,pendingTotal=pending_total,page=page,pageSize=50))
    def post(self,request):
        raise AuthError(403, 'insured_workflow_required', 'Maintain insured names and combinations through Case or Endorsement workflows.')
