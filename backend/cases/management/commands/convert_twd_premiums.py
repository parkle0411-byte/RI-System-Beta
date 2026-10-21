"""Preview by default; --apply performs the user-authorized TWD conversion."""
import json
from django.core.management.base import BaseCommand
from django.db import transaction
from audit.services import CLI_ACTOR,record_snapshot,record_audit
from cases.models import Case
from cases.premium_rounding import converted
from coordination.services import serialized, PRODUCTION_SOURCES

class Command(BaseCommand):
    help = "Convert eligible TWD premiums and preserve cases with payment/settlement history."
    def add_arguments(self, parser):
        parser.add_argument("--apply",action="store_true")
    def handle(self,*args,**options):
        changes=[]
        with serialized(PRODUCTION_SOURCES):
            for case in Case.objects.select_for_update().order_by("pk"):
                before=case.payload or {}
                after=converted(before,case.tw_ref)
                if after==before:continue
                changes.append({"caseId":case.pk,"rowVersion":case.row_version,"mode":after["premiumRounding"],"premiumInputsChanged":any(before.get(k)!=after.get(k) for k in ("originalPremium","reinsurers","performanceInstallments")),"transactionsChanged":before.get("transactions")!=after.get("transactions")})
                if options["apply"]:
                    case.payload=after;case.row_version+=1;case.updated_by=CLI_ACTOR["id"];case.save()
                    record_snapshot(entity_type="case",entity_id=case.case_uid,version=case.row_version,reason="twd_premium_precision_converted",data={"caseUid":str(case.case_uid),"twRef":case.tw_ref,"status":case.status,"rowVersion":case.row_version,"payload":after},created_by=CLI_ACTOR["id"])
                    record_audit(entity_type="case",entity_id=case.case_uid,action="convert_twd_premium_precision",before={"payload":before},after={"payload":after},actor=CLI_ACTOR,source="maintenance")
        self.stdout.write("RESULT "+json.dumps({"apply":options["apply"],"changes":changes}))
