from django.urls import path

from dashboard.learning_materials import views

app_name = "learning_materials"
urlpatterns = [
    path("", views.LearningMaterialListView.as_view(), name="home"),
    path("data/", views.LearningMaterialListDataView.as_view(), name="data"),
    path("create/", views.LearningMaterialCreateView.as_view(), name="create"),
    path("<int:pk>/", views.LearningMaterialDetailView.as_view(), name="detail"),
    path("<int:pk>/update/", views.LearningMaterialUpdateView.as_view(), name="update"),
    path("<int:pk>/delete/", views.LearningMaterialDeleteView.as_view(), name="delete"),
]
