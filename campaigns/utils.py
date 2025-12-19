from django_celery_beat.models import ClockedSchedule, PeriodicTask
from django.utils import timezone
import json

def schedule_campaign_send(campaign):
    clocked, _ = ClockedSchedule.objects.get_or_create(
        clocked_time=campaign.scheduled_at
    )

    PeriodicTask.objects.create(
        name=f"send-campaign-{campaign.id}",
        task="campaigns.tasks.send_campaign",
        clocked=clocked,
        one_off=True,
        enabled=True,
        args=json.dumps([campaign.id]),
    )
