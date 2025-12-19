import csv
import io
from datetime import timedelta

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from campaigns.models import (
    Campaign,
    CampaignRecipient,
    DeliveryLog,
    Recipient,
)
from campaigns.tasks import (
    send_campaign_emails,
    send_single_email,
    generate_and_send_campaign_report,
)


class DashboardViewTests(TestCase):
    def setUp(self) -> None:
        self.client = Client()

    def test_dashboard_empty(self) -> None:
        url = reverse("campaigns:dashboard")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "No campaigns yet.")

    def test_dashboard_with_campaign_stats(self) -> None:
        r1 = Recipient.objects.create(
            name="A", email="a@example.com", subscription_status="subscribed"
        )
        r2 = Recipient.objects.create(
            name="B", email="b@example.com", subscription_status="subscribed"
        )

        campaign = Campaign.objects.create(
            name="Test",
            subject="Subject",
            content="Hello",
            scheduled_time=timezone.now() + timedelta(hours=1),
            status=Campaign.Status.DRAFT,
        )
        campaign.recipients.add(r1, r2)

        DeliveryLog.objects.create(
            campaign=campaign,
            recipient=r1,
            recipient_email=r1.email,
            status=DeliveryLog.Status.SENT,
        )
        DeliveryLog.objects.create(
            campaign=campaign,
            recipient=r2,
            recipient_email=r2.email,
            status=DeliveryLog.Status.FAILED,
        )

        url = reverse("campaigns:dashboard")
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Test")
        self.assertContains(resp, "2")
        self.assertContains(resp, "1")


class CampaignCreateViewTests(TestCase):
    def setUp(self) -> None:
        self.client = Client()

    def test_get_campaign_form(self) -> None:
        url = reverse("campaigns:campaign_create")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Create New Campaign")

    def test_create_campaign_valid(self) -> None:
        url = reverse("campaigns:campaign_create")
        data = {
            "name": "Campaign 1",
            "subject": "Subj",
            "content": "Body",
            "scheduled_time": (timezone.localtime() + timedelta(hours=1)).strftime(
                "%Y-%m-%dT%H:%M"
            ),
            "status": Campaign.Status.DRAFT,
        }
        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Campaign.objects.filter(name="Campaign 1").exists())

    def test_create_campaign_past_time_rejected(self) -> None:
        url = reverse("campaigns:campaign_create")
        data = {
            "name": "Invalid",
            "subject": "Subj",
            "content": "Body",
            "scheduled_time": (timezone.localtime() - timedelta(hours=1)).strftime(
                "%Y-%m-%dT%H:%M"
            ),
            "status": Campaign.Status.DRAFT,
        }
        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Scheduled time must be in the future.")


class RecipientUploadViewTests(TestCase):
    def setUp(self) -> None:
        self.client = Client()

    def _upload_csv(self, rows):
        output = io.StringIO()
        writer = csv.DictWriter(
            output, fieldnames=["name", "email", "subscription_status"]
        )
        writer.writeheader()
        writer.writerows(rows)

        file = SimpleUploadedFile(
            "test.csv", output.getvalue().encode(), content_type="text/csv"
        )
        self.client.post(
            reverse("campaigns:recipient_upload"), {"file": file}
        )

    def test_upload_valid_recipients(self):
        rows = [
            {"name": "A", "email": "a@example.com", "subscription_status": "subscribed"},
            {"name": "B", "email": "b@example.com", "subscription_status": "unsubscribed"},
        ]
        self._upload_csv(rows)
        self.assertEqual(Recipient.objects.count(), 2)


class TaskExecutionTests(TestCase):
    def setUp(self) -> None:
        self.campaign = Campaign.objects.create(
            name="Scheduled",
            subject="Subj",
            content="<p>Hi</p>",
            scheduled_time=timezone.now() - timedelta(minutes=5),
            status=Campaign.Status.SCHEDULED,
        )
        self.recipient1 = Recipient.objects.create(
            name="R1", email="r1@example.com", subscription_status="subscribed"
        )
        self.recipient2 = Recipient.objects.create(
            name="R2", email="r2@example.com", subscription_status="unsubscribed"
        )

    def test_send_campaign_emails_creates_logs_for_subscribed_only(self):
        send_campaign_emails(self.campaign.id)

        self.assertTrue(
            CampaignRecipient.objects.filter(
                campaign=self.campaign,
                recipient=self.recipient1,
            ).exists()
        )
        self.assertFalse(
            CampaignRecipient.objects.filter(
                campaign=self.campaign,
                recipient=self.recipient2,
            ).exists()
        )

    def test_send_single_email_creates_log(self):
        send_single_email(self.campaign.id, self.recipient1.id)
        log = DeliveryLog.objects.get(
            campaign=self.campaign,
            recipient_email=self.recipient1.email,
        )
        self.assertIn(
            log.status,
            [DeliveryLog.Status.SENT, DeliveryLog.Status.FAILED],
        )

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        ADMIN_REPORT_EMAIL="admin@test.com",
        DEFAULT_FROM_EMAIL="no-reply@test.com",
    )
    def test_generate_and_send_campaign_report_sends_email(self):
        DeliveryLog.objects.create(
            campaign=self.campaign,
            recipient=self.recipient1,
            recipient_email=self.recipient1.email,
            status=DeliveryLog.Status.SENT,
        )

        generate_and_send_campaign_report(self.campaign.id)

        assert len(mail.outbox) == 1
