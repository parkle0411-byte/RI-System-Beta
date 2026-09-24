from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models

CURRENCIES = ["USD", "EUR", "JPY", "GBP", "HKD", "MYR"]
CURRENCY_CHOICES = [(c, c) for c in CURRENCIES]

year_month_validator = RegexValidator(
    regex=r"^\d{4}-(0[1-9]|1[0-2])$",
    message="Performance month must use YYYY-MM.",
)


class FxRate(models.Model):
    year_month = models.CharField(max_length=7, validators=[year_month_validator])
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    rate = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        validators=[MinValueValidator(0.000001), MaxValueValidator(1000)],
    )
    row_version = models.BigIntegerField(default=1)
    is_locked = models.BooleanField(default=False)
    locked_by = models.CharField(max_length=255, null=True, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    lock_reason = models.CharField(max_length=255, null=True, blank=True)
    created_by = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.CharField(max_length=255)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ri_fx_rates"
        constraints = [
            models.UniqueConstraint(
                fields=["year_month", "currency"], name="ri_fx_rates_month_currency_unique"
            )
        ]
        indexes = [models.Index(fields=["year_month", "currency"], name="ri_fx_rates_month_idx")]
        ordering = ["-year_month", "currency"]

    def __str__(self):
        return f"{self.year_month} {self.currency} = {self.rate}"
