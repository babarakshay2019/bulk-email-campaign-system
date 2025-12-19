from django import forms
from django.utils import timezone

from .models import Campaign


class CampaignForm(forms.ModelForm):
    scheduled_time = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        help_text="Date and time when the campaign should start sending.",
    )

    class Meta:
        model = Campaign
        fields = ["name", "subject", "content", "scheduled_time", "status"]

    def clean_scheduled_time(self):
        value = self.cleaned_data["scheduled_time"]
        # Normalize to aware datetime in current timezone for reliable comparison.
        if timezone.is_naive(value):
            value = timezone.make_aware(value, timezone.get_current_timezone())
        now_local = timezone.localtime(timezone.now())
        value_local = timezone.localtime(value)
        if value_local <= now_local:
            raise forms.ValidationError("Scheduled time must be in the future.")
        return value


class RecipientUploadForm(forms.Form):
    file = forms.FileField(
        help_text="Upload a CSV file with columns: name,email,subscription_status"
    )


