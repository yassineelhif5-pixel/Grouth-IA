"""Login by username: re-applies the (idempotent) SQL migrations so existing databases receive 0012_usernames.sql."""
from django.db import migrations

from apps.core.sql_migrations import sql_operations


class Migration(migrations.Migration):
    dependencies = [("core", "0002_prompt2_schema")]
    operations = sql_operations()
