import csv
import io
import json

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import ListView, DetailView, CreateView
from django_celery_beat.models import ClockedSchedule, PeriodicTask

from .forms import CampaignForm, RecipientUploadForm
from .models import Campaign, DeliveryLog, Recipient


class DashboardView(ListView):
    template_name = "campaigns/dashboard.html"
    context_object_name = "campaigns"

    def get_queryset(self):
        return (
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


class CampaignCreateView(CreateView):
    model = Campaign
    form_class = CampaignForm
    template_name = "campaigns/campaign_form.html"

    def get_initial(self):
        return {
            "scheduled_time": timezone.now() + timezone.timedelta(hours=1),
            "status": Campaign.Status.DRAFT,
        }

    def form_valid(self, form):
        campaign = form.save()
        messages.success(self.request, "Campaign created successfully.")

        if campaign.status == Campaign.Status.SCHEDULED:
            clocked = ClockedSchedule.objects.create(
                clocked_time=timezone.localtime(campaign.scheduled_time)
            )

            PeriodicTask.objects.create(
                name=f"send-campaign-{campaign.id}",
                task="campaigns.tasks.send_campaign",
                clocked=clocked,
                one_off=True,
                enabled=True,
                args=json.dumps([campaign.id]),
            )

        return redirect("campaigns:dashboard")


class CampaignDetailView(DetailView):
    model = Campaign
    template_name = "campaigns/campaign_detail.html"
    context_object_name = "campaign"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        logs = self.object.delivery_logs.select_related("recipient").order_by(
            "-sent_at"
        )

        context.update(
            {
                "logs": logs,
                "sent_count": logs.filter(status=DeliveryLog.Status.SENT).count(),
                "failed_count": logs.filter(status=DeliveryLog.Status.FAILED).count(),
                "total": logs.count(),
            }
        )
        return context


class RecipientUploadView(View):
    template_name = "campaigns/recipient_upload.html"

    def get(self, request):
        form = RecipientUploadForm()
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        form = RecipientUploadForm(request.POST, request.FILES)

        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        file = form.cleaned_data["file"]

        try:
            data = file.read().decode("utf-8")
        except UnicodeDecodeError:
            messages.error(
                request, "Unable to decode file. Please upload UTF-8 encoded CSV."
            )
            return redirect("campaigns:recipient_upload")

        reader = csv.DictReader(io.StringIO(data))

        existing_emails = set(Recipient.objects.values_list("email", flat=True))

        recipients_to_create = []
        created_count = skipped_count = invalid_rows = 0

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
                    recipients_to_create,
                    ignore_conflicts=True,
                )
            created_count = len(created_objects)
        except IntegrityError:
            for recipient in recipients_to_create:
                try:
                    recipient.save()
                    created_count += 1
                except IntegrityError:
                    skipped_count += 1

        messages.success(
            request,
            f"Upload complete. Created: {created_count}, "
            f"Skipped: {skipped_count}, Invalid rows: {invalid_rows}.",
        )

        return redirect("campaigns:dashboard")
