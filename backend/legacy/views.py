from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import FileResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from ri_system.authz import RIPermission,NoStoreMixin,object_body
from cases import storage
from .models import LegacyTransaction,ImportBatch,LegacyAudit
from .services import fail,representation


class TransactionsView(NoStoreMixin,APIView):
    permission_classes=[RIPermission]
    # Entry service restricts writes to owned, nonhistorical drafts.
    permission_map={'GET':'legacy.read','POST':'legacy.read','PATCH':'legacy.read'}

    def get(self,request):
        qs=LegacyTransaction.objects.filter(status__in=['draft','confirmed']).select_related('reference_transaction')
        uid=request.query_params.get('id')
        if uid:
            try:t=qs.get(pk=uid)
            except (LegacyTransaction.DoesNotExist,ValueError,ValidationError):fail('Transaction not found.',404)
            value=representation(t,request.ri_principal)
            value['original']=t.original
            value['audit']=[dict(action=e.action,actor=e.actor_name,at=e.occurred_at.isoformat(),reason=e.reason)
                for e in LegacyAudit.objects.filter(entity=str(t.uid)).order_by('occurred_at')]
            return Response(value)
        q=str(request.query_params.get('q') or '').strip()[:200]
        if q:qs=qs.filter(Q(reference__icontains=q)|Q(number__icontains=q)|Q(data__statementNo__icontains=q)|
            Q(data__insured__icontains=q)|Q(data__insuredCn__icontains=q)|Q(data__party__icontains=q))
        if request.query_params.get('sourceOnly')=='1':qs=qs.filter(status='confirmed')
        if request.query_params.get('status'):qs=qs.filter(status=request.query_params['status'])
        try:page=min(1000000,max(1,int(request.query_params.get('page',1))));size=min(100,max(1,int(request.query_params.get('size',25))))  # 2026-11-10：頁碼上限，超大頁碼回空白頁而非資料庫錯誤
        except ValueError:fail('Invalid pagination.')
        return Response(dict(count=qs.count(),page=page,role=request.ri_principal.role_code,readOnly=request.ri_principal.role_code not in ('sales','general_manager','admin'),
            rows=[representation(t,request.ri_principal) for t in qs.order_by('-created_at','uid')[(page-1)*size:page*size]]))


    def post(self,request):
        from coordination.services import serialized,PRODUCTION_SOURCES
        from .entries import create
        with serialized(PRODUCTION_SOURCES):
            t=create(request.ri_principal,object_body(request))
            return Response(representation(t,request.ri_principal),status=201)

    def patch(self,request):
        from coordination.services import serialized,PRODUCTION_SOURCES
        from .entries import change
        with serialized(PRODUCTION_SOURCES):
            t=change(request.ri_principal,object_body(request))
            return Response(representation(t,request.ri_principal))


class ImportView(NoStoreMixin,APIView):
    permission_classes=[RIPermission]
    permission_map={'GET':'accounts.manage'}

    def get(self,request):
        if request.query_params.get('download'):
            try:b=ImportBatch.objects.get(pk=request.query_params['download'])
            except (ImportBatch.DoesNotExist,ValueError,ValidationError):fail('Import batch not found.',404)
            from cases.documents import content_disposition
            r=FileResponse(storage.open_read(b.storage_key),content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            r['Content-Disposition']=content_disposition(b.filename)
            return r
        return Response(dict(readOnly=True,batches=[dict(id=str(b.pk),filename=b.filename,status=b.status,
            sha256=b.sha256,createdAt=b.created_at.isoformat(),manifest=b.manifest)
            for b in ImportBatch.objects.order_by('-created_at')[:100]]))


class OptionsView(NoStoreMixin,APIView):
    permission_classes=[RIPermission]
    permission_map={'GET':'legacy.read','POST':'accounts.manage'}

    def get(self,request):
        from personnel.models import Personnel
        from masterdata.models import MasterRecord
        from .models import LegacyReason
        from .ledger import RULE_NAMES
        return Response(dict(reasons=list((LegacyReason.objects.all() if request.ri_principal.role_code=='admin' else LegacyReason.objects.filter(active=True)).order_by('sort_order','code').values('code','label','active')),
            rules=[dict(code=k,label=v) for k,v in RULE_NAMES.items()],
            people=list(Personnel.objects.filter(is_active=True).order_by('name').values('id','name','role_code')),
            parties=list(MasterRecord.objects.filter(is_active=True,entity_type__in=['reinsured','reinsurer','foreign_broker']).order_by('name').values('name','entity_type'))))

    def post(self,request):
        import re
        from coordination.services import serialized,PRODUCTION_SOURCES
        from .models import LegacyReason
        from .services import audit
        b=object_body(request);code=b.get('code');label=b.get('label');active=b.get('active',True)
        if not isinstance(code,str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}',code):fail('Enter a valid reason code.')
        if not isinstance(label,str) or not label.strip() or len(label)>200 or type(active) is not bool:fail('Enter a reason label and active state.')
        with serialized(PRODUCTION_SOURCES):
            prior=LegacyReason.objects.select_for_update().filter(pk=code).first()
            before={'label':prior.label,'active':prior.active} if prior else {}
            item,_=LegacyReason.objects.update_or_create(code=code,defaults={'label':label.strip(),'active':active})
            audit(request.ri_principal,'reason:'+code,'reason_saved',before,{'label':item.label,'active':item.active})
        return Response({'ok':True})
