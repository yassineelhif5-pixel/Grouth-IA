"""Claude as default AI model: re-applies the idempotent SQL migrations (adds 0017)."""
from django.db import migrations

from apps.core.sql_migrations import sql_operations


class Migration(migrations.Migration):
    dependencies = [("core", "0005_site_access")]
    operations = sql_operations()
