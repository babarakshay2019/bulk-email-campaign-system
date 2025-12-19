from django.db import models
from django.utils import timezone


class Recipient(models.Model):
    class SubscriptionStatus(models.TextChoices):
        SUBSCRIBED = "subscribed", "Subscribed"
        UNSUBSCRIBED = "unsubscribed", "Unsubscribed"

    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    subscription_status = models.CharField(
        max_length=20,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.SUBSCRIBED,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"


class Campaign(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SCHEDULED = "scheduled", "Scheduled"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    name = models.CharField(max_length=255)
    subject = models.CharField(max_length=255)
    content = models.TextField(help_text="Plain text or HTML content")
    scheduled_time = models.DateTimeField()
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    recipients = models.ManyToManyField(
        Recipient, through="CampaignRecipient", related_name="campaigns"
    )

    def __str__(self) -> str:
        return self.name

    @property
    def total_recipients(self) -> int:
        return self.recipients.filter(
            subscription_status=Recipient.SubscriptionStatus.SUBSCRIBED
        ).count()


class CampaignRecipient(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE)
    recipient = models.ForeignKey(Recipient, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("campaign", "recipient")

    def __str__(self) -> str:
        return f"{self.campaign} -> {self.recipient}"


class DeliveryLog(models.Model):
    class Status(models.TextChoices):
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    campaign = models.ForeignKey(
        Campaign, on_delete=models.CASCADE, related_name="delivery_logs"
    )
    recipient = models.ForeignKey(
        Recipient, on_delete=models.CASCADE, related_name="delivery_logs"
    )
    recipient_email = models.EmailField()
    status = models.CharField(max_length=10, choices=Status.choices)
    failure_reason = models.TextField(blank=True)
    sent_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=["campaign", "status"]),
            models.Index(fields=["recipient_email"]),
        ]

    def __str__(self) -> str:
        return f"{self.campaign} -> {self.recipient_email}: {self.status}"

