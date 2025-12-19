from __future__ import annotations

import csv
import io

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import CampaignForm, RecipientUploadForm
from .models import Campaign, DeliveryLog, Recipient
from .tasks import process_scheduled_campaigns


def dashboard(request):
    """
    List all campaigns with aggregate statistics.
    """
    campaigns = (
        Campaign.objects.all()
        .annotate(
            subscribed_recipients_count=Count(
                "recipients",
                filter=Q(
                    recipients__subscription_status=Recipient.SubscriptionStatus.SUBSCRIBED
                ),
                distinct=True,
            ),
            sent_count=Count(
                "delivery_logs",
                filter=Q(delivery_logs__status=DeliveryLog.Status.SENT),
                distinct=True,
            ),
            failed_count=Count(
                "delivery_logs",
                filter=Q(delivery_logs__status=DeliveryLog.Status.FAILED),
                distinct=True,
            ),
        )
        .order_by("-created_at")
    )
    return render(request, "campaigns/dashboard.html", {"campaigns": campaigns})


def campaign_create(request):
    """
    Create a new campaign.
    """
    if request.method == "POST":
        form = CampaignForm(request.POST)
        if form.is_valid():
            campaign = form.save()
            messages.success(request, "Campaign created successfully.")
            if campaign.status == Campaign.Status.SCHEDULED:
                process_scheduled_campaigns.delay()
            return redirect("campaigns:dashboard")
    else:
        form = CampaignForm(
            initial={
                "scheduled_time": timezone.now()
                + timezone.timedelta(hours=1),
                "status": Campaign.Status.DRAFT,
            }
        )

    return render(
        request,
        "campaigns/campaign_form.html",
        {"form": form},
    )


def campaign_detail(request, pk: int):
    """
    Show details and delivery logs for a single campaign.
    """
    campaign = get_object_or_404(Campaign, pk=pk)
    logs = campaign.delivery_logs.select_related("recipient").order_by("-sent_at")
    sent_count = logs.filter(status=DeliveryLog.Status.SENT).count()
    failed_count = logs.filter(status=DeliveryLog.Status.FAILED).count()
    total = logs.count()

    return render(
        request,
        "campaigns/campaign_detail.html",
        {
            "campaign": campaign,
            "logs": logs,
            "sent_count": sent_count,
            "failed_count": failed_count,
            "total": total,
        },
    )


def recipient_upload(request):
    """
    Bulk upload recipients from a CSV file.
    Expected columns: name, email, subscription_status
    """
    if request.method == "POST":
        form = RecipientUploadForm(request.POST, request.FILES)
        if form.is_valid():
            file = form.cleaned_data["file"]
            try:
                data = file.read().decode("utf-8")
            except UnicodeDecodeError:
                messages.error(
                    request,
                    "Unable to decode file. Please upload UTF-8 encoded CSV.",
                )
                return redirect("campaigns:recipient_upload")

            reader = csv.DictReader(io.StringIO(data))

            created_count = 0
            skipped_count = 0
            invalid_rows = 0

            recipients_to_create = []
            existing_emails = set(
                Recipient.objects.values_list("email", flat=True)
            )

            for row in reader:
                name = (row.get("name") or "").strip()
                email = (row.get("email") or "").strip().lower()
                status = (row.get("subscription_status") or "subscribed").lower()

                if not name or not email:
                    invalid_rows += 1
                    continue

                if status not in dict(Recipient.SubscriptionStatus.choices):
                    status = Recipient.SubscriptionStatus.SUBSCRIBED

                if email in existing_emails:
                    skipped_count += 1
                    continue

                recipients_to_create.append(
                    Recipient(
                        name=name,
                        email=email,
                        subscription_status=status,
                    )
                )
                existing_emails.add(email)

            try:
                with transaction.atomic():
                    created_objects = Recipient.objects.bulk_create(
                        recipients_to_create, ignore_conflicts=True
                    )
                created_count = len(created_objects)
            except IntegrityError:
                # Fallback: create one-by-one to avoid full failure.
                for recipient in recipients_to_create:
                    try:
                        recipient.save()
                        created_count += 1
                    except IntegrityError:
                        skipped_count += 1

            messages.success(
                request,
                f"Upload complete. Created: {created_count}, "
                f"Skipped (duplicates): {skipped_count}, "
                f"Invalid rows: {invalid_rows}.",
            )
            return redirect("campaigns:dashboard")
    else:
        form = RecipientUploadForm()

    return render(
        request,
        "campaigns/recipient_upload.html",
        {"form": form},
    )

