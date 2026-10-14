"""Case Loss Record 0-year rule; all API writes roll back."""
import copy
import json
import uuid

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client, override_settings

from cases.draft import loss_record_save_errors, validate_announce_ready
from cases.models import Case
from cases.workflow import build_endorsement_payload, build_renewal_payload
from personnel.models import Personnel


class Rollback(Exception):
    pass


def base(**changes):
    payload = dict(
        originalInsured="ZZ Loss Zero", reinsured="ZZ Cedant", classOfBusiness="ZZ Class",
        newOrRenew="New", currency="USD", policyFrom="2026-01-01", policyTo="2026-12-31",
        originalPremium=1000, riCommPct=10, taxPct=0, paymentTermsDays=30,
        reinsurers=[dict(name="ZZ Re", sharePct=100, premium=1000, riCommPct=5, taxPct=0)],
        lossAdvisedDate="2026-01-01", lossRecordYears=0, lossRecord=[],
    )
    payload.update(changes)
    return payload


def call(client, method, payload):
    return getattr(client, method)(
        "/api/cases", data=json.dumps(payload), content_type="application/json",
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )


try:
    with transaction.atomic(), override_settings(AUDIT_LOG_PAUSED=True):
        marker = uuid.uuid4().hex[:10]
        user = get_user_model().objects.create_user(username="zz.loss.zero." + marker, password="Test-Loss-0-Password")
        person = Personnel.objects.create(
            name="ZZ Loss Zero " + marker, department="reinsurance", role_code="sales",
            auth_user_id=str(user.pk), account_status="active", created_by="qa", updated_by="qa",
        )
        client = Client(enforce_csrf_checks=True, HTTP_HOST="localhost", raise_request_exception=False)
        client.force_login(user)
        client.get("/api/auth/csrf")

        for changes, expected in (
            ({"lossAdvisedDate": ""}, "Loss record advised by broker on"),
            ({"lossRecordYears": None}, "Loss history years"),
            ({"newOrRenew": "Renew"}, "only for a New case"),
            ({"lossRecord": [{"date": "2025-01-01", "cause": "Fire", "lossPaid": 0}]}, "must be empty"),
        ):
            response = call(client, "post", {"case": base(**changes)})
            assert response.status_code == 400 and expected in response.json()["message"], response.content
        assert not Case.objects.filter(payload__originalInsured="ZZ Loss Zero").exists()

        response = call(client, "post", {"case": base()})
        assert response.status_code == 201, response.content
        case_uid = response.json()["case"]["caseUid"]
        saved = Case.objects.get(case_uid=case_uid)
        assert saved.payload["lossRecordYears"] == 0 and saved.payload["lossRecord"] == []
        assert saved.owner_personnel_id == person.pk
        issues = {item["field"] for item in validate_announce_ready(saved.payload, allow_zero_loss_years=True)}
        assert "lossRecordYears" not in issues and "lossRecord" not in issues, issues

        edit = copy.deepcopy(saved.payload)
        edit["lossRecordText"] = "No prior insurance"
        response = call(client, "put", {"caseUid": case_uid, "rowVersion": saved.row_version, "case": edit})
        assert response.status_code == 200, response.content
        saved.refresh_from_db()

        edit = copy.deepcopy(saved.payload)
        edit["lossRecordYears"] = None
        response = call(client, "put", {"caseUid": case_uid, "rowVersion": saved.row_version, "case": edit})
        assert response.status_code == 400 and "Loss history years" in response.json()["message"], response.content
        saved.refresh_from_db()
        assert saved.payload["lossRecordYears"] == 0

        endorsement = build_endorsement_payload(saved.payload, "TWTEST", 0)
        assert endorsement["lossRecordYears"] == 0 and not loss_record_save_errors(endorsement, case_kind="endorsement")
        renewal = build_renewal_payload(saved.payload, "TWTEST")
        assert renewal["lossRecordYears"] == 0 and renewal["newOrRenew"] == "Renew"
        assert loss_record_save_errors(renewal, case_kind="renewal")
        assert "lossRecordYears" in {item["field"] for item in validate_announce_ready(
            renewal, allow_zero_loss_years=True, case_kind="renewal")}
        renewal["lossRecordYears"] = 1
        assert not loss_record_save_errors(renewal, case_kind="renewal")

        positive = base(lossRecordYears=5, lossRecord=[{"date": "2025-01-01", "cause": "Fire", "lossPaid": 0}])
        response = call(client, "post", {"case": positive})
        assert response.status_code == 201, response.content
        print("PASS Loss Record save, 0-year New, Endorsement inheritance, Renewal correction and Announce validation")
        raise Rollback()
except Rollback:
    pass
