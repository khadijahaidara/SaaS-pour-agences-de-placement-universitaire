from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from . import views

app_name = "api"

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register("dossiers", views.DossierViewSet, basename="dossier")
router.register("payments", views.PaymentViewSet, basename="payment")
router.register("offers", views.OfferViewSet, basename="offer")
router.register("workflows", views.WorkflowViewSet, basename="workflow")
router.register("custom-fields", views.CustomFieldViewSet, basename="custom-field")

urlpatterns = [
    path("v1/me/", views.MeView.as_view(), name="me"),
    path("v1/", include(router.urls)),
    path("schema/", SpectacularAPIView.as_view(permission_classes=[], authentication_classes=[]), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api:schema", permission_classes=[], authentication_classes=[]), name="docs"),
    path("redoc/", SpectacularRedocView.as_view(url_name="api:schema", permission_classes=[], authentication_classes=[]), name="redoc"),
]
