from rest_framework import serializers

from .models import FxRate


class FxRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = FxRate
        fields = [
            "id", "year_month", "currency", "rate", "row_version",
            "is_locked", "locked_at", "lock_reason", "updated_at",
        ]
