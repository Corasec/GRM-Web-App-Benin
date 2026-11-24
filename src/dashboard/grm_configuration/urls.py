from django.urls import path

from dashboard.grm_configuration import views

app_name = "grm_configuration"
urlpatterns = [
    path("", views.ConfigurationHomeView.as_view(), name="home"),
    path("types/new/", views.IssueTypeCreateView.as_view(), name="type_create"),
    path("types/<int:pk>/", views.IssueTypeUpdateView.as_view(), name="type_update"),
    path("subtypes/new/", views.IssueSubTypeCreateView.as_view(), name="subtype_create"),
    path("subtypes/<int:pk>/", views.IssueSubTypeUpdateView.as_view(), name="subtype_update"),
    path("categories/new/", views.IssueCategoryCreateView.as_view(), name="category_create"),
    path("categories/<int:pk>/", views.IssueCategoryUpdateView.as_view(), name="category_update"),
    path("<str:kind>/<int:pk>/delete/", views.ConfigurationDeleteView.as_view(), name="delete"),
]
