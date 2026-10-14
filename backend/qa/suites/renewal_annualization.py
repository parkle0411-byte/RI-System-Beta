"""Disposable API regression: renewal uses the complete current policy chain."""

import json
import os
from datetime import date

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client

from cases.models import Case
from personnel.models import Personnel


assert os.environ.get("RI_DISPOSABLE_QA") == "true"


def check(label, condition):
    assert condition, label
    print("PASS " + label, flush=True)


class Rollback(Exception):
    pass


try:
    with transaction.atomic():
        user = get_user_model().objects.create_user(username="zz.renewal.fix", password="QA-Renewal-8!")
        person = Personnel.objects.create(
            name="QA Renewal Fix", department="reinsurance", role_code="sales",
            auth_user_id=str(user.pk), account_status="active", created_by="qa", updated_by="qa")
        client = Client(enforce_csrf_checks=True, HTTP_HOST="localhost", raise_request_exception=False)

        def call(method, url, body=None):
            client.get("/api/auth/csrf")
            opts = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}
            if body is not None:
                opts.update(data=json.dumps(body), content_type="application/json")
            return getattr(client, method)(url, **opts)

        login = call("post", "/api/auth/login", {"username": user.username, "password": "QA-Renewal-8!"})
        check("sales test actor authenticated", login.status_code == 200)

        base = {"policyFrom": "2046-03-01", "policyTo": "2047-03-01", "currency": "USD",
                "originalPremium": 10000, "reinsurers": [
                    {"name": "QA Re A", "sharePct": 60, "premium": 8000},
                    {"name": "QA Re B", "sharePct": 40, "premium": 7000}],
                "installmentEnabled": False, "performanceInstallments": []}
        root = Case.objects.create(case_kind="original", status="closed", tw_ref="QA-RN-2046",
                                   effective_date=date(2046, 3, 1), expiration_date=date(2047, 3, 1),
                                   payload=base, owner_personnel=person, created_by="qa", updated_by="qa")
        add = {**base, "parentTwRef": root.tw_ref, "endoEffectiveDate": "2046-06-24",
               "originalPremium": 500, "reinsurers": [
                   {"name": "QA Re A", "sharePct": 60, "premium": 400},
                   {"name": "QA Re B", "sharePct": 40, "premium": 350}]}
        e1 = Case.objects.create(case_kind="endorsement", parent_case=root, status="closed",
                                 tw_ref="QA-RN-2046-E01", effective_date=date(2046, 3, 1),
                                 expiration_date=date(2047, 3, 1), payload=add, owner_personnel=person,
                                 created_by="qa", updated_by="qa")
        reduce = {**base, "parentTwRef": root.tw_ref, "endoEffectiveDate": "2046-11-21",
                  "originalPremium": -100, "reinsurers": [
                      {"name": "QA Re A", "sharePct": 60, "premium": -80},
                      {"name": "QA Re B", "sharePct": 40, "premium": -70}]}
        e2 = Case.objects.create(case_kind="endorsement", parent_case=root, status="closed",
                                 tw_ref="QA-RN-2046-E02", effective_date=date(2046, 3, 1),
                                 expiration_date=date(2047, 3, 1), payload=reduce, owner_personnel=person,
                                 created_by="qa", updated_by="qa")

        old_actions = call("get", f"/api/case-workflow?caseUid={root.case_uid}").json()["workflow"]["actions"]
        latest_actions = call("get", f"/api/case-workflow?caseUid={e2.case_uid}").json()["workflow"]["actions"]
        check("only latest Confirmed case offers renewal", not old_actions["canRenew"] and latest_actions["canRenew"])

        old = call("post", "/api/case-workflow", {"action": "create_renewal", "caseUid": str(root.case_uid),
                                                   "rowVersion": root.row_version})
        check("renewal from stale root is refused", old.status_code == 409
              and old.json()["error"] == "latest_endorsement_required")
        response = call("post", "/api/case-workflow", {"action": "create_renewal", "caseUid": str(e2.case_uid),
                                                        "rowVersion": e2.row_version})
        check("renewal from latest case succeeds", response.status_code == 201)
        draft = Case.objects.get(case_uid=response.json()["case"]["caseUid"])
        check("annualized 100% premium is 10,365", draft.payload["originalPremium"] == 10365)
        check("reinsurer annual premiums are 8,292 and 7,255.50",
              [r["premium"] for r in draft.payload["reinsurers"]] == [8292, 7255.5])
        check("new renewal keeps latest risk and shifts policy dates",
              draft.case_kind == "renewal" and draft.parent_case_id is None
              and draft.payload["policyFrom"] == "2047-03-01"
              and draft.payload["policyTo"] == "2048-03-01")
        root.refresh_from_db(); e1.refresh_from_db(); e2.refresh_from_db()
        check("previous premiums remain unchanged",
              [root.payload["originalPremium"], e1.payload["originalPremium"], e2.payload["originalPremium"]]
              == [10000, 500, -100])

        installment_payload = {**base, "policyFrom": "2046-07-01", "policyTo": "2047-07-01",
                               "originalPremium": 1000, "installmentEnabled": True,
                               "performanceInstallments": [
                                   {"id": "I1", "performanceMonth": "2046-07", "paymentBaseDate": "2046-07-05", "premium": 300},
                                   {"id": "I2", "performanceMonth": "2046-08", "paymentBaseDate": "2046-08-05", "premium": 700}]}
        installment_root = Case.objects.create(
            case_kind="original", status="closed", tw_ref="QA-RN-INSTALLMENTS-2046",
            effective_date=date(2046, 7, 1), expiration_date=date(2047, 7, 1),
            payload=installment_payload, owner_personnel=person, created_by="qa", updated_by="qa")
        response = call("post", "/api/case-workflow", {"action": "create_renewal",
                                                        "caseUid": str(installment_root.case_uid),
                                                        "rowVersion": installment_root.row_version})
        check("installment renewal Draft is created", response.status_code == 201)
        installment_draft = Case.objects.get(case_uid=response.json()["case"]["caseUid"])
        check("old installment values remain available for editing",
              installment_draft.payload["installmentEnabled"] is True
              and [r["performanceMonth"] for r in installment_draft.payload["performanceInstallments"]]
              == ["2046-07", "2046-08"])

        def announce_issues(row):
            result = call("post", "/api/case-announce", {"caseUid": str(row.case_uid),
                "rowVersion": row.row_version, "confirmed": True, "documentIds": []})
            assert result.status_code == 400 and result.json()["error"] == "case_not_ready", result.content
            return result.json()["issues"]

        old_issues = announce_issues(installment_draft)
        check("old-year installment dates are blocked before Announce",
              len([i for i in old_issues if "within renewal coverage" in i["label"]]) == 4)
        corrected = dict(installment_draft.payload)
        corrected["performanceInstallments"] = [dict(row) for row in corrected["performanceInstallments"]]
        corrected["performanceInstallments"][0].update(performanceMonth="2047-07", paymentBaseDate="2047-07-05")
        corrected["performanceInstallments"][1].update(performanceMonth="2047-08", paymentBaseDate="2047-08-05")
        Case.objects.filter(pk=installment_draft.pk).update(payload=corrected)
        new_issues = announce_issues(installment_draft)
        check("corrected renewal installment dates pass the new date rule",
              not any("within renewal coverage" in i["label"] for i in new_issues))
        raise Rollback()
except Rollback:
    pass

print("12/12 renewal annualization API checks passed; database changes rolled back", flush=True)
