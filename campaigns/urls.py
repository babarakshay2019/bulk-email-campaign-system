from django.urls import path

from . import views

app_name = "campaigns"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("campaigns/new/", views.campaign_create, name="campaign_create"),
    path("campaigns/<int:pk>/", views.campaign_detail, name="campaign_detail"),
    path("recipients/upload/", views.recipient_upload, name="recipient_upload"),
]


