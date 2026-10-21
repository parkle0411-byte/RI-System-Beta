from rest_framework import serializers

from .models import MasterRecord
from .lloyds_market import effective_payload


class MasterRecordSerializer(serializers.ModelSerializer):
    entityType = serializers.CharField(source="entity_type")
    isActive = serializers.BooleanField(source="is_active")
    rowVersion = serializers.IntegerField(source="row_version")
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["payload"] = effective_payload(instance.entity_type, instance.name, data["payload"], ratings=self.context.get("lloydsRatings"))
        return data

    class Meta:
        model = MasterRecord
        fields = [
            "id",
            "entityType",
            "code",
            "name",
            "isActive",
            "payload",
            "rowVersion",
            "updatedAt",
        ]
