import json
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder


def snapshot(instance) -> dict[str, Any]:
    """JSON-safe snapshot of a model instance (secret fields removed)."""
    data = {f.attname if f.is_relation else f.name: getattr(instance, f.attname) for f in instance._meta.concrete_fields}
    for name in getattr(instance, "SECRET_FIELDS", ()):
        data.pop(name, None)
    return json.loads(json.dumps(data, cls=DjangoJSONEncoder))
