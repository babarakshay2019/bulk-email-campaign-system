from __future__ import annotations

import csv
import io
from datetime import timedelta

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from campaigns.models import Campaign, DeliveryLog, Recipient
from campaigns.tasks import (
    generate_and_send_campaign_report,
    process_scheduled_campaigns,
    send_campaign_emails,
    send_single_email,
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
            failure_reason="Error",
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
        self.assertContains(resp, "Create Campaign")

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


class CampaignDetailViewTests(TestCase):
    def setUp(self) -> None:
        self.client = Client()
        self.campaign = Campaign.objects.create(
            name="Detail Campaign",
            subject="Subj",
            content="Body",
            scheduled_time=timezone.now() + timedelta(hours=1),
            status=Campaign.Status.DRAFT,
        )

    def test_campaign_detail_no_logs(self) -> None:
        url = reverse("campaigns:campaign_detail", args=[self.campaign.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "No delivery logs yet.")

    def test_campaign_detail_with_logs(self) -> None:
        r = Recipient.objects.create(
            name="R", email="r@example.com", subscription_status="subscribed"
        )
        DeliveryLog.objects.create(
            campaign=self.campaign,
            recipient=r,
            recipient_email=r.email,
            status=DeliveryLog.Status.SENT,
        )
        url = reverse("campaigns:campaign_detail", args=[self.campaign.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "r@example.com")


class RecipientUploadViewTests(TestCase):
    def setUp(self) -> None:
        self.client = Client()

    def _upload_csv(self, rows: list[dict[str, str]]) -> None:
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["name", "email", "subscription_status"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        content = output.getvalue().encode("utf-8")
        file = SimpleUploadedFile("test.csv", content, content_type="text/csv")
        url = reverse("campaigns:recipient_upload")
        self.client.post(url, {"file": file})

    def test_upload_valid_recipients(self) -> None:
        rows = [
            {"name": "A", "email": "a@example.com", "subscription_status": "subscribed"},
            {"name": "B", "email": "b@example.com", "subscription_status": "unsubscribed"},
        ]
        self._upload_csv(rows)
        self.assertEqual(Recipient.objects.count(), 2)

    def test_upload_skips_duplicates_and_invalid(self) -> None:
        Recipient.objects.create(
            name="Existing",
            email="dup@example.com",
            subscription_status="subscribed",
        )
        rows = [
            {"name": "New", "email": "new@example.com", "subscription_status": "subscribed"},
            {"name": "Dup", "email": "dup@example.com", "subscription_status": "subscribed"},
            {"name": "", "email": "no-name@example.com", "subscription_status": "subscribed"},
        ]
        self._upload_csv(rows)
        # Existing + one new valid
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

    def test_process_scheduled_campaigns_marks_in_progress(self) -> None:
        process_scheduled_campaigns()
        self.campaign.refresh_from_db()
        # With Celery eager mode, the campaign may complete immediately.
        self.assertIn(
            self.campaign.status,
            [Campaign.Status.IN_PROGRESS, Campaign.Status.COMPLETED],
        )

    def test_send_campaign_emails_creates_logs_for_subscribed_only(self) -> None:
        send_campaign_emails(self.campaign.id)
        from campaigns.models import CampaignRecipient

        self.assertTrue(
            CampaignRecipient.objects.filter(
                campaign=self.campaign, recipient=self.recipient1
            ).exists()
        )
        self.assertFalse(
            CampaignRecipient.objects.filter(
                campaign=self.campaign, recipient=self.recipient2
            ).exists()
        )

    def test_send_single_email_creates_log(self) -> None:
        send_single_email(self.campaign.id, self.recipient1.id)
        log = DeliveryLog.objects.get(
            campaign=self.campaign, recipient_email=self.recipient1.email
        )
        self.assertIn(log.status, [DeliveryLog.Status.SENT, DeliveryLog.Status.FAILED])

    def test_generate_and_send_campaign_report_sends_email(self) -> None:
        DeliveryLog.objects.create(
            campaign=self.campaign,
            recipient=self.recipient1,
            recipient_email=self.recipient1.email,
            status=DeliveryLog.Status.SENT,
        )
        generate_and_send_campaign_report(self.campaign.id)
        self.assertGreaterEqual(len(mail.outbox), 1)
        self.assertIn("Campaign Report", mail.outbox[0].subject)


