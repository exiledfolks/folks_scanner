from django.urls import path
from .views import WorkingNodesView

urlpatterns = [
    path('subscription/', WorkingNodesView.as_view(), name='subscription'),
]
