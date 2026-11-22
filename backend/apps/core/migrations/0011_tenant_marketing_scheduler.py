"""Tenant Marketing Center scheduled draft generation schema (migration 0022)."""
from django.db import migrations

from apps.core.sql_migrations import sql_operations


class Migration(migrations.Migration):
    dependencies = [("core", "0010_tenant_marketing_campaigns")]
    operations = sql_operations()
