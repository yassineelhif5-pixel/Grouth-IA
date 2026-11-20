"""PROMPT 3 (licences, visibility programmes, paid plans, trial): re-applies the idempotent SQL migrations (0013–0015)."""
from django.db import migrations

from apps.core.sql_migrations import sql_operations


class Migration(migrations.Migration):
    dependencies = [("core", "0003_usernames")]
    operations = sql_operations()
