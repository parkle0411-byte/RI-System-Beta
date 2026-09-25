import re
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import record_audit, record_snapshot, request_id_from
from ri_system.authz import NoStoreMixin, RIPermission, actor_from

from .models import CURRENCIES, FxRate
from .serializers import FxRateSerializer

YEAR_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def fx_state(rate):
    """Snapshot / Audit 內容，欄位與 Alpha 的 jsonb_build_object 相同（rate 為數字）。"""
    return {
        "id": rate.id,
        "yearMonth": rate.year_month,
        "currency": rate.currency,
        "rate": float(rate.rate),
        "rowVersion": rate.row_version,
        "isLocked": rate.is_locked,
    }


class FxRatesView(NoStoreMixin, APIView):
    # 對應 Alpha 的 fx.read / fx.write：Finance Staff 只能讀；Finance Manager 與 Admin 可新增及修改。
    permission_classes = [RIPermission]
    permission_map = {"GET": "fx.read", "POST": "fx.write"}

    def get(self, request):
        # 與 Alpha 相同：月份由新到舊，同月份內依 USD, EUR, JPY, GBP, HKD, MYR 排序
        rates = sorted(FxRate.objects.all(), key=lambda r: CURRENCIES.index(r.currency))
        rates.sort(key=lambda r: r.year_month, reverse=True)
        return Response({
            "ok": True,
            "displayVersion": "V 0.003",
            "rates": FxRateSerializer(rates, many=True).data,
            "policy": {
                "baseCurrency": "TWD",
                "baseRate": 1,
                "maintainedCurrencies": CURRENCIES,
                "externalRateSource": False,
                "lockedMonthsEditable": False,
                "completeMonthRequired": True,
            },
        })

    def post(self, request):
        body = request.data
        year_month = str(body.get("yearMonth", "")).strip()
        if not YEAR_MONTH_RE.match(year_month):
            return Response(
                {"error": "invalid_month", "message": "Performance month must use YYYY-MM."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        rates_input = body.get("rates")
        if not isinstance(rates_input, list) or len(rates_input) != len(CURRENCIES):
            return Response(
                {"error": "incomplete_rates", "message": "All six currency rates are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        seen = set()
        parsed = []
        for row in rates_input:
            currency = str(row.get("currency", "")).strip().upper()
            if currency not in CURRENCIES or currency in seen:
                return Response(
                    {
                        "error": "invalid_currency",
                        "message": "Rates must contain USD, EUR, JPY, GBP, HKD and MYR exactly once.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                rate = Decimal(str(row.get("rate")))
            except (InvalidOperation, TypeError):
                rate = None
            if rate is None or rate <= 0 or rate > 1000:
                return Response(
                    {
                        "error": "invalid_rate",
                        "message": f"{currency} Rate to TWD must be greater than 0 and no more than 1000.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            row_version = row.get("rowVersion")
            if row_version is not None:
                try:
                    row_version = int(row_version)
                except (TypeError, ValueError):
                    return Response(
                        {"error": "invalid_version", "message": f"{currency} has an invalid row version."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            seen.add(currency)
            parsed.append({"currency": currency, "rate": rate, "row_version": row_version})

        if CURRENCIES and any(c not in seen for c in CURRENCIES):
            return Response(
                {"error": "incomplete_rates", "message": "All six currency rates are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        actor_info = actor_from(request.ri_principal)
        actor = actor_info["id"]
        request_id = request_id_from(request)

        with transaction.atomic():
            existing = {
                r.currency: r
                for r in FxRate.objects.select_for_update().filter(year_month=year_month)
            }

            if any(r.is_locked for r in existing.values()):
                return Response(
                    {
                        "error": "month_locked",
                        "message": "This Performance month is locked because its Production Report is closed.",
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            for row in parsed:
                current = existing.get(row["currency"])
                if current and current.row_version != row["row_version"]:
                    return Response(
                        {
                            "error": "version_conflict",
                            "message": f"{row['currency']} changed elsewhere. Reload the month before saving.",
                            "currency": row["currency"],
                            "currentRowVersion": current.row_version,
                        },
                        status=status.HTTP_409_CONFLICT,
                    )
                if not current and row["row_version"] is not None:
                    return Response(
                        {
                            "error": "version_conflict",
                            "message": f"{row['currency']} no longer matches the stored month. Reload before saving.",
                        },
                        status=status.HTTP_409_CONFLICT,
                    )

            saved = []
            now = timezone.now()
            for row in parsed:
                current = existing.get(row["currency"])
                before = fx_state(current) if current else None
                if current:
                    current.rate = row["rate"]
                    current.row_version += 1
                    current.updated_by = actor
                    current.updated_at = now
                    current.save(update_fields=["rate", "row_version", "updated_by", "updated_at"])
                    saved.append(current)
                else:
                    created = FxRate.objects.create(
                        year_month=year_month,
                        currency=row["currency"],
                        rate=row["rate"],
                        created_by=actor,
                        updated_by=actor,
                    )
                    saved.append(created)

                row_saved = saved[-1]
                after = fx_state(row_saved)
                record_snapshot(
                    entity_type="fx_rate", entity_id=row_saved.id, version=row_saved.row_version,
                    reason="monthly_fx_rates_saved", data=after, created_by=actor,
                )
                # Alpha 的 FX 只寫 snapshot、沒有 Audit 事件；VM 依「所有新增與修改都要有 Audit」補上。
                record_audit(
                    entity_type="fx_rate", entity_id=row_saved.id,
                    action="update_fx_rate" if before else "create_fx_rate",
                    before=before, after=after, actor=actor_info, request_id=request_id,
                    metadata={"displayVersion": "V 0.003", "milestone": "monthly-fx-rates"},
                )

        saved.sort(key=lambda r: CURRENCIES.index(r.currency))
        return Response({
            "ok": True,
            "displayVersion": "V 0.003",
            "yearMonth": year_month,
            "rates": FxRateSerializer(saved, many=True).data,
        })
