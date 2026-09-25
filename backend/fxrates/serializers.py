from rest_framework import serializers

from .models import FxRate


class FxRateSerializer(serializers.ModelSerializer):
    """
    輸出格式與 Hatchable Alpha 的 api/fx-rates.js serialize() 完全一致：
    駝峰欄位、rate 為數字（不是字串）、lockReason 空值回傳空字串。
    """

    yearMonth = serializers.CharField(source="year_month", read_only=True)
    rate = serializers.FloatField(read_only=True)
    rowVersion = serializers.IntegerField(source="row_version", read_only=True)
    isLocked = serializers.BooleanField(source="is_locked", read_only=True)
    lockedAt = serializers.DateTimeField(source="locked_at", read_only=True)
    lockReason = serializers.SerializerMethodField()
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = FxRate
        fields = [
            "id", "yearMonth", "currency", "rate", "rowVersion",
            "isLocked", "lockedAt", "lockReason", "updatedAt",
        ]

    def get_lockReason(self, obj):
        return obj.lock_reason or ""
