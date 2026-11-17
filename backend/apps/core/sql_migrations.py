from pathlib import Path

from django.conf import settings
from django.db import migrations


def sql_operations() -> list:
    sql_dir = Path(settings.REPO_ROOT) / "database" / "migrations"
    return [migrations.RunSQL(sql=p.read_text(encoding="utf-8"), reverse_sql=migrations.RunSQL.noop)
            for p in sorted(sql_dir.glob("*.sql"))]
