"""API REST v1. Chaque requête est limitée à l'agence de la clé (ou du membre connecté).

Les vues ne contiennent aucune règle métier : elles valident l'entrée puis appellent
les mêmes services que l'interface web (dossiers.services, agencies.customization).
"""
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from agencies.customization import apply_offer, validate_custom_data
from agencies.models import CustomField, ServiceOffer
from dossiers import services
from dossiers.models import Dossier, Payment, WorkflowTemplate

from . import serializers as s
from .models import ApiKey
from .permissions import request_agency

User = get_user_model()


def scoped_dossiers(request):
    """Clé API : toute l'agence. Session : mêmes règles que l'interface (conseiller = ses dossiers)."""
    if isinstance(request.auth, ApiKey):
        return Dossier.objects.filter(agency=request.auth.agency)
    return Dossier.objects.for_user(request.user)


class MeView(APIView):
    @extend_schema(summary="Agence associée à la clé", responses={200: dict})
    def get(self, request):
        agency = request_agency(request)
        return Response({
            "agency": {"name": agency.name, "slug": agency.slug, "currency": agency.currency,
                       "plan": agency.plan, "operational": agency.is_operational},
            "via": "api_key" if isinstance(request.auth, ApiKey) else "session",
        })


@extend_schema(parameters=[
    OpenApiParameter("status", str, description="Filtrer par statut (active, blocked, refused, completed, cancelled)"),
    OpenApiParameter("destination", str, description="Pays de destination (contient)"),
    OpenApiParameter("q", str, description="Recherche : nom, courriel, référence"),
    OpenApiParameter("updated_since", str, description="Date ISO 8601 : dossiers modifiés depuis"),
])
class DossierViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                     mixins.UpdateModelMixin, viewsets.GenericViewSet):
    lookup_field = "reference"
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = scoped_dossiers(self.request).select_related("student", "counselor", "agency")
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("destination"):
            qs = qs.filter(destination_country__icontains=p["destination"])
        if p.get("q"):
            q = p["q"]
            qs = qs.filter(Q(reference__icontains=q) | Q(student__email__icontains=q)
                           | Q(student__last_name__icontains=q) | Q(student__first_name__icontains=q))
        if p.get("updated_since"):
            dt = parse_datetime(p["updated_since"])
            if dt:
                qs = qs.filter(updated_at__gte=dt)
        if self.action == "retrieve":
            qs = qs.prefetch_related("stages", "document_requests__stage", "fees", "payments")
        return qs.order_by("-updated_at")

    def get_serializer_class(self):
        return {
            "list": s.DossierListSerializer,
            "create": s.DossierCreateSerializer,
            "partial_update": s.DossierUpdateSerializer,
            "update": s.DossierUpdateSerializer,
        }.get(self.action, s.DossierDetailSerializer)

    def _detail(self, dossier, code=status.HTTP_200_OK):
        dossier = self.get_queryset().get(pk=dossier.pk) if self.action != "create" else dossier
        return Response(s.DossierDetailSerializer(dossier, context={"request": self.request}).data, status=code)

    @extend_schema(summary="Créer un dossier", request=s.DossierCreateSerializer, responses={201: s.DossierDetailSerializer})
    def create(self, request, *args, **kwargs):
        agency = request_agency(request)
        ser = s.DossierCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = dict(ser.validated_data)
        workflow = get_object_or_404(WorkflowTemplate, pk=d.pop("workflow_id"), agency=agency)
        counselor = None
        if d.get("counselor_email"):
            counselor = get_object_or_404(User, email__iexact=d.pop("counselor_email"), agency=agency,
                                          role__in=[User.Role.AGENCY_ADMIN, User.Role.COUNSELOR])
        else:
            d.pop("counselor_email", None)
            if not isinstance(request.auth, ApiKey) and not request.user.is_agency_admin:
                counselor = request.user
        offer_id = d.pop("offer_id", None)
        custom = validate_custom_data(agency, d.pop("custom_data", {}))
        dossier, _ = services.create_dossier(agency=agency, actor=request.user, workflow=workflow,
                                             counselor=counselor, custom_data=custom, **d)
        if offer_id:
            apply_offer(dossier, request.user, get_object_or_404(ServiceOffer, pk=offer_id, agency=agency))
        dossier = Dossier.objects.prefetch_related("stages", "document_requests", "fees", "payments").get(pk=dossier.pk)
        return Response(s.DossierDetailSerializer(dossier).data, status=status.HTTP_201_CREATED)

    @extend_schema(summary="Modifier les informations d'un dossier", request=s.DossierUpdateSerializer,
                   responses={200: s.DossierDetailSerializer})
    def partial_update(self, request, *args, **kwargs):
        dossier = self.get_object()
        ser = s.DossierUpdateSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        data = dict(ser.validated_data)
        if "custom_data" in data:
            merged = {**dossier.custom_data, **data.pop("custom_data")}
            dossier.custom_data = validate_custom_data(dossier.agency, merged)
        for field, value in data.items():
            setattr(dossier, field, value)
        dossier.save()
        services.log_event(dossier, request.user, "note", "Informations du dossier mises à jour (API).",
                           visible_to_student=False)
        return self._detail(dossier)

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    @extend_schema(summary="Terminer l'étape en cours", request=s.AdvanceSerializer, responses={200: s.DossierDetailSerializer})
    @action(detail=True, methods=["post"])
    def advance(self, request, reference=None):
        dossier = self.get_object()
        ser = s.AdvanceSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        services.advance_stage(dossier, request.user, next_due_date=ser.validated_data.get("next_due_date"))
        return self._detail(dossier)

    @extend_schema(summary="Changer le statut", request=s.StatusSerializer, responses={200: s.DossierDetailSerializer})
    @action(detail=True, methods=["post"], url_path="status")
    def set_status(self, request, reference=None):
        dossier = self.get_object()
        ser = s.StatusSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        services.set_status(dossier, request.user, ser.validated_data["status"], ser.validated_data["reason"])
        return self._detail(dossier)

    @extend_schema(summary="Enregistrer un paiement", request=s.PaymentCreateSerializer, responses={201: s.PaymentSerializer})
    @action(detail=True, methods=["post"])
    def payments(self, request, reference=None):
        dossier = self.get_object()
        ser = s.PaymentCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        payment = services.record_payment(dossier, request.user, **ser.validated_data)
        return Response(s.PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)

    @extend_schema(summary="Demander une pièce", request=s.DocumentRequestCreateSerializer, responses={201: s.DocumentSerializer})
    @action(detail=True, methods=["post"])
    def documents(self, request, reference=None):
        dossier = self.get_object()
        ser = s.DocumentRequestCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        doc = services.request_document(dossier, request.user, **ser.validated_data)
        return Response(s.DocumentSerializer(doc).data, status=status.HTTP_201_CREATED)

    @extend_schema(summary="Appliquer une prestation", request=s.ApplyOfferSerializer, responses={200: s.DossierDetailSerializer})
    @action(detail=True, methods=["post"], url_path="apply-offer")
    def apply_offer(self, request, reference=None):
        dossier = self.get_object()
        ser = s.ApplyOfferSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        offer = get_object_or_404(ServiceOffer, pk=ser.validated_data["offer_id"], agency=dossier.agency)
        apply_offer(dossier, request.user, offer)
        return self._detail(dossier)


@extend_schema(parameters=[
    OpenApiParameter("since", str, description="Date (AAAA-MM-JJ) de début"),
    OpenApiParameter("until", str, description="Date (AAAA-MM-JJ) de fin"),
])
class PaymentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = s.PaymentSerializer
    lookup_field = "receipt_number"

    def get_queryset(self):
        qs = Payment.objects.filter(dossier__in=scoped_dossiers(self.request)).select_related("dossier")
        p = self.request.query_params
        if p.get("since"):
            qs = qs.filter(paid_on__gte=p["since"])
        if p.get("until"):
            qs = qs.filter(paid_on__lte=p["until"])
        return qs.order_by("-paid_on", "-recorded_at")


class OfferViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = s.OfferSerializer

    def get_queryset(self):
        return ServiceOffer.objects.filter(agency=request_agency(self.request), is_active=True).prefetch_related("installments")


class WorkflowViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = s.WorkflowSerializer

    def get_queryset(self):
        return WorkflowTemplate.objects.filter(agency=request_agency(self.request), is_active=True).prefetch_related("stages")


class CustomFieldViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = s.CustomFieldSerializer
    lookup_field = "key"

    def get_queryset(self):
        return CustomField.objects.filter(agency=request_agency(self.request), is_active=True)
