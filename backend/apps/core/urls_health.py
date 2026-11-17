from django.db import connection
from django.http import JsonResponse
from django.urls import path


def live(_request):
    return JsonResponse({"status": "ok"})


def ready(_request):
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
        return JsonResponse({"status": "ok"})
    except Exception:  # noqa: BLE001
        return JsonResponse({"status": "down"}, status=503)


urlpatterns = [path("live", live), path("ready", ready)]
