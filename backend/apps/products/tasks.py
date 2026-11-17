from apps.observability.tasks_base import TracedTask
from config.celery import app

from .onboarding import run_onboarding


@app.task(base=TracedTask, name="products.onboarding", module="products", max_retries=0, autoretry_for=())
def onboarding_task(product_id: str):
    return run_onboarding(product_id)
