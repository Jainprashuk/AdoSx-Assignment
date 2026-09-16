"""Project routes.

Everything lives under /api/. There is no Django-rendered page: the screen is
the React app in frontend/, which talks to these endpoints.
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("reconciliation.urls")),
]
