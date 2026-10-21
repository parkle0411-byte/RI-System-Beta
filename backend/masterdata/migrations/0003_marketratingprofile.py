from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("masterdata", "0002_masterrecord_ri_master_records_type_name_unique")]
    operations = [migrations.CreateModel(
        name="MarketRatingProfile",
        fields=[
            ("market_code", models.CharField(max_length=40, primary_key=True, serialize=False)),
            ("ratings", models.JSONField(default=list)),
            ("row_version", models.BigIntegerField(default=1)),
            ("created_by", models.CharField(max_length=120)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_by", models.CharField(max_length=120)),
            ("updated_at", models.DateTimeField(auto_now=True)),
        ],
        options={"db_table": "ri_market_rating_profiles"},
    )]
