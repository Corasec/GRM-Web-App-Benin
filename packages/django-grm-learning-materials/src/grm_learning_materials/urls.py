from django.urls import path

from . import views

app_name = "grm_learning_materials"
urlpatterns = [
    path("", views.LearningMaterialListView.as_view(), name="home"),
    path("data/", views.LearningMaterialListDataView.as_view(), name="data"),
    path("create/", views.LearningMaterialCreateView.as_view(), name="create"),
    path("<int:pk>/", views.LearningMaterialDetailView.as_view(), name="detail"),
    path("<int:pk>/update/", views.LearningMaterialUpdateView.as_view(), name="update"),
    path("<int:pk>/delete/", views.LearningMaterialDeleteView.as_view(), name="delete"),
]
