"""API routes. Read-only in this stage; the upload endpoint arrives in stage 9."""

from django.urls import path

from . import views

urlpatterns = [
    path("batches/", views.batches, name="batches"),
    path("orgs/", views.orgs, name="orgs"),
    path("discrepancies/", views.discrepancies, name="discrepancies"),
]
