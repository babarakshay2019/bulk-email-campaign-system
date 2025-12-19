from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("campaigns/", include("campaigns.urls")),
    path("", RedirectView.as_view(pattern_name="campaigns:dashboard", permanent=False)),
]
