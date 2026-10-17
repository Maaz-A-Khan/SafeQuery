from django.urls import path

from core import views
from core.audit import views as audit_views

urlpatterns = [
    path("connect/", views.connect, name="connect"),
    path("schema/<int:connection_id>/", views.schema, name="schema"),
    path("ask/<int:connection_id>/", views.ask, name="ask"),
    path("log/", audit_views.log, name="log"),
    path("log/<int:entry_id>/", audit_views.log_detail, name="log_detail"),
]
