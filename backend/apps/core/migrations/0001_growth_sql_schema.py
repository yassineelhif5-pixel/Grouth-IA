"""Applies the versioned SQL migrations (database/migrations/*.sql) through Django.

Django migrations are the single delivery pipeline: the SQL files are generated from the
declarative schema (database/schema) and are idempotent, so re-applying them is safe.
Business tables are mapped by unmanaged models (managed=False) — no competing DDL.
"""
from pathlib import Path

from django.conf import settings
from django.db import migrations

SQL_DIR = Path(settings.REPO_ROOT) / "database" / "migrations"
FILES = sorted(p for p in SQL_DIR.glob("*.sql"))


def _op(path: Path) -> migrations.RunSQL:
    return migrations.RunSQL(sql=path.read_text(encoding="utf-8"), reverse_sql=migrations.RunSQL.noop)


class Migration(migrations.Migration):
    initial = True
    dependencies: list = []
    run_before = [("contenttypes", "0001_initial"), ("django_celery_beat", "0001_initial")]
    operations = [_op(p) for p in FILES]
