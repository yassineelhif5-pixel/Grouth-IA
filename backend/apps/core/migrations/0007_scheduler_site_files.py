"""Allow the 'site_files' scheduler category: re-applies the idempotent SQL migrations (adds 0018)."""
from django.db import migrations

from apps.core.sql_migrations import sql_operations


class Migration(migrations.Migration):
    dependencies = [("core", "0006_default_claude")]
    operations = sql_operations()
