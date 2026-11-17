"""PROMPT 2: re-applies the (idempotent) SQL migrations so existing databases receive the additive
changes (new tables, ADD COLUMN IF NOT EXISTS, updated CHECK constraints, reference data)."""
from django.db import migrations

from .growth_sql import sql_operations


class Migration(migrations.Migration):
    dependencies = [("core", "0001_growth_sql_schema")]
    operations = sql_operations()
