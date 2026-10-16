from django.urls import include, path

from planner.api.views import spa_index

urlpatterns = [
    path("api/", include("planner.api.urls")),
    # Everything else is the React single-page app (production build only).
    path("", spa_index),
]
