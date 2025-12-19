from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils import timezone

from .models import Campaign, CampaignRecipient, DeliveryLog, Recipient



@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=30,
    retry_kwargs={"max_retries": 3},
)
def send_campaign(self, campaign_id: int) -> None:
    campaign = Campaign.objects.get(pk=campaign_id)

    if campaign.status != Campaign.Status.SCHEDULED:
        return

    campaign.status = Campaign.Status.IN_PROGRESS
    campaign.updated_at = timezone.now()
    campaign.save(update_fields=["status", "updated_at"])

    send_campaign_emails.delay(campaign.id)


@shared_task
def send_campaign_emails(campaign_id: int) -> None:
    campaign = Campaign.objects.get(pk=campaign_id)

    recipients = Recipient.objects.filter(
        subscription_status=Recipient.SubscriptionStatus.SUBSCRIBED
    )

    for recipient in recipients:
        CampaignRecipient.objects.get_or_create(
            campaign=campaign,
            recipient=recipient,
        )

        already_sent = DeliveryLog.objects.filter(
            campaign=campaign,
            recipient=recipient,
        ).exists()

        if already_sent:
            continue

        send_single_email(campaign_id, recipient.id)

    _finalize_campaign(campaign_id)


def send_single_email(campaign_id: int, recipient_id: int) -> None:
    campaign = Campaign.objects.get(pk=campaign_id)
    recipient = Recipient.objects.get(pk=recipient_id)

    msg = EmailMultiAlternatives(
        subject=campaign.subject,
        body=campaign.content,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient.email],
    )
    msg.attach_alternative(campaign.content, "text/html")

    try:
        msg.send()
        DeliveryLog.objects.create(
            campaign=campaign,
            recipient=recipient,
            recipient_email=recipient.email,
            status=DeliveryLog.Status.SENT,
            sent_at=timezone.now(),
        )
    except Exception as exc:
        DeliveryLog.objects.create(
            campaign=campaign,
            recipient=recipient,
            recipient_email=recipient.email,
            status=DeliveryLog.Status.FAILED,
            failure_reason=str(exc),
            sent_at=timezone.now(),
        )


def _finalize_campaign(campaign_id: int) -> None:
    campaign = Campaign.objects.get(pk=campaign_id)

    total_targets = CampaignRecipient.objects.filter(
        campaign=campaign
    ).count()

    total_logs = DeliveryLog.objects.filter(
        campaign=campaign
    ).count()

    if total_targets == 0:
        return

    if total_logs >= total_targets:
        campaign.status = Campaign.Status.COMPLETED
        campaign.updated_at = timezone.now()
        campaign.save(update_fields=["status", "updated_at"])

        generate_and_send_campaign_report.delay(campaign_id)


@shared_task
def generate_and_send_campaign_report(campaign_id: int) -> None:
    campaign = Campaign.objects.get(pk=campaign_id)
    logs = campaign.delivery_logs.order_by("id")

    sent_count = logs.filter(status=DeliveryLog.Status.SENT).count()
    failed_count = logs.filter(status=DeliveryLog.Status.FAILED).count()

    report_text = [
        f"Campaign: {campaign.name}",
        f"Subject: {campaign.subject}",
        f"Scheduled Time: {campaign.scheduled_time}",
        f"Status: {campaign.status}",
        "",
        f"Total: {logs.count()}",
        f"Sent: {sent_count}",
        f"Failed: {failed_count}",
    ]

    csv_lines = ["recipient_email,status,failure_reason,sent_at"]
    for log in logs:
        failure = (log.failure_reason or "").replace(",", ";")
        csv_lines.append(
            f"{log.recipient_email},{log.status},{failure},{log.sent_at}"
        )

    admin_email = getattr(settings, "ADMIN_REPORT_EMAIL", None)
    if not admin_email:
        return

    msg = EmailMultiAlternatives(
        subject=f"Campaign Report: {campaign.name}",
        body="\n".join(report_text),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[admin_email],
    )

    msg.attach(
        filename=f"campaign_{campaign_id}_report.csv",
        content="\n".join(csv_lines),
        mimetype="text/csv",
    )
    msg.send()


