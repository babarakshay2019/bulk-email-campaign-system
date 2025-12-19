from django.contrib import admin

from .models import Campaign, CampaignRecipient, DeliveryLog, Recipient


@admin.register(Recipient)
class RecipientAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "subscription_status", "created_at")
    list_filter = ("subscription_status",)
    search_fields = ("name", "email")


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ("name", "subject", "scheduled_time", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("name", "subject")
    date_hierarchy = "scheduled_time"


@admin.register(CampaignRecipient)
class CampaignRecipientAdmin(admin.ModelAdmin):
    list_display = ("campaign", "recipient", "created_at")
    search_fields = ("campaign__name", "recipient__email")


@admin.register(DeliveryLog)
class DeliveryLogAdmin(admin.ModelAdmin):
    list_display = ("campaign", "recipient_email", "status", "sent_at")
    list_filter = ("status", "campaign")
    search_fields = ("recipient_email", "failure_reason")

