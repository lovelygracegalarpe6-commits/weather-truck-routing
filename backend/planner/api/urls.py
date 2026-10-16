from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.HealthView.as_view(), name="health"),
    path("geocode/", views.GeocodeView.as_view(), name="geocode"),
    path("plan/", views.PlanView.as_view(), name="plan"),
    path("heatmap/", views.HeatmapView.as_view(), name="heatmap"),
]
