from __future__ import annotations

from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils import timezone

from .models import Campaign, CampaignRecipient, DeliveryLog, Recipient


@shared_task
def process_scheduled_campaigns() -> None:
    """
    Periodic task that finds due campaigns and enqueues sending tasks.
    """
    now = timezone.now()
    due_campaigns = Campaign.objects.filter(
        status=Campaign.Status.SCHEDULED, scheduled_time__lte=now
    )

    for campaign in due_campaigns:
        with transaction.atomic():
            campaign = (
                Campaign.objects.select_for_update()
                .filter(pk=campaign.pk)
                .first()
            )
            if not campaign:
                continue
            if campaign.status != Campaign.Status.SCHEDULED:
                continue

            campaign.status = Campaign.Status.IN_PROGRESS
            campaign.save(update_fields=["status", "updated_at"])

        send_campaign_emails.delay(campaign_id=campaign.id)


@shared_task
def send_campaign_emails(campaign_id: int) -> None:
    """
    Send campaign emails to all subscribed recipients.
    """
    campaign = Campaign.objects.get(pk=campaign_id)
    recipients = (
        Recipient.objects.filter(
            subscription_status=Recipient.SubscriptionStatus.SUBSCRIBED
        )
        .distinct()
        .order_by("id")
    )

    for recipient in recipients:
        CampaignRecipient.objects.get_or_create(
            campaign=campaign, recipient=recipient
        )
        send_single_email.delay(campaign_id, recipient.id)


@shared_task
def send_single_email(campaign_id: int, recipient_id: int) -> None:
    """
    Send a single email and persist a DeliveryLog.
    """
    campaign = Campaign.objects.get(pk=campaign_id)
    recipient = Recipient.objects.get(pk=recipient_id)

    subject = campaign.subject
    from_email = settings.DEFAULT_FROM_EMAIL
    to = [recipient.email]

    msg = EmailMultiAlternatives(
        subject=subject,
        body=campaign.content,
        from_email=from_email,
        to=to,
    )
    msg.attach_alternative(campaign.content, "text/html")

    try:
        msg.send()
        DeliveryLog.objects.create(
            campaign=campaign,
            recipient=recipient,
            recipient_email=recipient.email,
            status=DeliveryLog.Status.SENT,
        )
    except Exception as exc:  # noqa: BLE001
        DeliveryLog.objects.create(
            campaign=campaign,
            recipient=recipient,
            recipient_email=recipient.email,
            status=DeliveryLog.Status.FAILED,
            failure_reason=str(exc),
        )

    _update_campaign_status_if_complete(campaign_id)


def _update_campaign_status_if_complete(campaign_id: int) -> None:
    """
    Update campaign status when all recipients processed.
    """
    campaign = Campaign.objects.get(pk=campaign_id)
    total_subscribed = Recipient.objects.filter(
        subscription_status=Recipient.SubscriptionStatus.SUBSCRIBED
    ).count()

    if total_subscribed == 0:
        return

    total_logs = campaign.delivery_logs.count()
    if total_logs >= total_subscribed:
        campaign.status = Campaign.Status.COMPLETED
        campaign.updated_at = timezone.now()
        campaign.save(update_fields=["status", "updated_at"])

        generate_and_send_campaign_report.delay(campaign_id)


@shared_task
def generate_and_send_campaign_report(campaign_id: int) -> None:
    """
    Build a simple text report, store as CSV file, and email to admin.
    """
    campaign = Campaign.objects.get(pk=campaign_id)
    logs = campaign.delivery_logs.select_related("recipient").order_by("id")

    sent_count = logs.filter(status=DeliveryLog.Status.SENT).count()
    failed_count = logs.filter(status=DeliveryLog.Status.FAILED).count()
    total = logs.count()

    summary_lines = [
        f"Campaign: {campaign.name}",
        f"Subject: {campaign.subject}",
        f"Scheduled Time: {campaign.scheduled_time}",
        f"Status: {campaign.status}",
        "",
        f"Total: {total}",
        f"Sent: {sent_count}",
        f"Failed: {failed_count}",
        "",
        "Detailed delivery logs:",
    ]

    for log in logs:
        summary_lines.append(
            f"{log.sent_at.isoformat()} | {log.recipient_email} | "
            f"{log.status} | {log.failure_reason or ''}"
        )

    report_text = "\n".join(summary_lines)

    csv_lines = ["recipient_email,status,failure_reason,sent_at"]
    for log in logs:
        failure = (log.failure_reason or "").replace(",", ";")
        csv_lines.append(
            f"{log.recipient_email},{log.status},{failure},{log.sent_at.isoformat()}"
        )
    csv_content = "\n".join(csv_lines)

    admin_email = getattr(settings, "ADMIN_REPORT_EMAIL", None)
    if not admin_email:
        return

    subject = f"[Campaign Report] {campaign.name}"
    msg = EmailMultiAlternatives(
        subject=subject,
        body=report_text,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[admin_email],
    )
    msg.attach(
        filename=f"campaign_{campaign_id}_report.csv",
        content=csv_content,
        mimetype="text/csv",
    )
    msg.send()


