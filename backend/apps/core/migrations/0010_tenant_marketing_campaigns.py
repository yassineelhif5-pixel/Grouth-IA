"""Tenant Marketing Center campaign and editorial backlog schema (migration 0021)."""
from django.db import migrations

from apps.core.sql_migrations import sql_operations


class Migration(migrations.Migration):
    dependencies = [("core", "0009_tenant_marketing_center")]
    operations = sql_operations()
