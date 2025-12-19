from django.urls import path
from .views import (
    DashboardView,
    CampaignCreateView,
    CampaignDetailView,
    RecipientUploadView,
)

app_name = "campaigns"

urlpatterns = [
    path("", DashboardView.as_view(), name="dashboard"),
    path("create/", CampaignCreateView.as_view(), name="campaign_create"),
    path("<int:pk>/", CampaignDetailView.as_view(), name="campaign_detail"),
    path("recipients/upload/", RecipientUploadView.as_view(), name="recipient_upload"),
]


