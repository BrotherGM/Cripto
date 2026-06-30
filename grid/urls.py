from django.urls import path

from grid import views

app_name = "grid"

urlpatterns = [
    path("", views.dashboard_index, name="dashboard"),
    path("<int:pk>/", views.strategy_chart, name="strategy_chart"),
    path("<int:pk>/data.json", views.strategy_chart_data, name="strategy_chart_data"),
]
