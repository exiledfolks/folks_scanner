import logging

from django.conf import settings
from config.celery import app
from .actions import run_full_scan_sync, push_subscription_to_github

task_logger = logging.getLogger("task")


@app.task(bind=True, ignore_result=False, queue=settings.CELERY_TASK_DEFAULT_QUEUE)
def run_full_scan_sync_task(self):
    """Celery task to trigger run_full_scan_sync."""
    run_full_scan_sync()


@app.task(bind=True, ignore_result=False, queue=settings.CELERY_TASK_DEFAULT_QUEUE)
def push_subscription_to_github_task(self):
    """Celery task to trigger push_subscription_to_github."""
    push_subscription_to_github()