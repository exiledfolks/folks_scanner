import logging

from django.conf import settings
from config.celery import app
from .actions import run_full_scan_sync

task_logger = logging.getLogger("task")


@app.task(bind=True, ignore_result=False, queue=settings.CELERY_TASK_DEFAULT_QUEUE)
def run_full_scan_sync_task(self):
    """Celery task to trigger run_full_scan_sync."""
    run_full_scan_sync()
