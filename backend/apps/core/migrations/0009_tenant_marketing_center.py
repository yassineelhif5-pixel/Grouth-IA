"""Tenant Marketing Center schema (migration 0020)."""
from django.db import migrations

from apps.core.sql_migrations import sql_operations


class Migration(migrations.Migration):
    dependencies = [("core", "0008_seed_ai_models")]
    operations = sql_operations()
