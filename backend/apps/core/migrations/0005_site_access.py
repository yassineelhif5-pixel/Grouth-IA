"""Forced correction (site access via GitHub): re-applies the idempotent SQL migrations (adds 0016)."""
from django.db import migrations

from apps.core.sql_migrations import sql_operations


class Migration(migrations.Migration):
    dependencies = [("core", "0004_prompt3")]
    operations = sql_operations()
