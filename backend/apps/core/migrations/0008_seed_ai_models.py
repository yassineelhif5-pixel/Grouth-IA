"""Pre-populate AI providers and their models: re-applies the idempotent SQL migrations (adds 0019)."""
from django.db import migrations

from apps.core.sql_migrations import sql_operations


class Migration(migrations.Migration):
    dependencies = [("core", "0007_scheduler_site_files")]
    operations = sql_operations()
