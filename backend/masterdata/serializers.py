from rest_framework import serializers

from .models import MasterRecord


class MasterRecordSerializer(serializers.ModelSerializer):
    entityType = serializers.CharField(source="entity_type")
    isActive = serializers.BooleanField(source="is_active")
    rowVersion = serializers.IntegerField(source="row_version")
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

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
