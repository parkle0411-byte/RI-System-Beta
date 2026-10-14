from django.db import models


class OperationLock(models.Model):
    """Stable transaction lock, including months with no reports or FX rows yet."""

    key = models.CharField(max_length=80, primary_key=True)

    class Meta:
        db_table = "ri_operation_locks"

