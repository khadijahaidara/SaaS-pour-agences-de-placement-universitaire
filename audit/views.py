"""Journal d'audit de l'agence (filtres + export CSV)."""
import csv
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from billing.services import has_feature
from dossiers.permissions import agency_perm_required

from .models import ACTION_GROUPS, AuditLog
from .services import record

User = get_user_model()


def _filtered(request):
    agency = request.user.agency
    qs = AuditLog.objects.filter(agency=agency).select_related("actor")
    group = request.GET.get("groupe", "")
    if group in dict(ACTION_GROUPS):
        qs = qs.filter(action__startswith=group + ".")
    actor = request.GET.get("membre", "")
    if actor.isdigit():
        qs = qs.filter(actor_id=int(actor))
    period = request.GET.get("periode", "30")
    if period in {"1", "7", "30", "90", "365"}:
        qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=int(period)))
    if request.GET.get("sensibles"):
        from .models import SENSITIVE

        qs = qs.filter(action__in=SENSITIVE)
    return qs


@agency_perm_required("audit.view")
def journal(request):
    agency = request.user.agency
    feature = has_feature(agency, "audit_log")
    qs = _filtered(request) if feature else AuditLog.objects.none()
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    members = User.objects.filter(agency=agency, role__in=[User.Role.AGENCY_ADMIN, User.Role.COUNSELOR]).order_by("last_name")
    since = timezone.now() - timedelta(days=30)
    base = AuditLog.objects.filter(agency=agency, created_at__gte=since) if feature else AuditLog.objects.none()
    stats = {
        "logins": base.filter(action="auth.login").count(),
        "failed": base.filter(action__in=["auth.login_failed", "auth.2fa_failed"]).count(),
        "exports": base.filter(action__in=["dossier.exported", "payment.exported"]).count(),
        "downloads": base.filter(action="document.downloaded").count(),
    }
    return render(request, "audit/journal.html", {
        "page": page, "groups": ACTION_GROUPS, "members": members, "querystring": params.urlencode(),
        "feature": feature, "stats": stats, "tab": "journal",
    })


@agency_perm_required("audit.view")
def journal_export(request):
    if not has_feature(request.user.agency, "audit_log"):
        return HttpResponse(status=403)
    record("dossier.exported", metadata={"export": "journal d'audit"})
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="journal-audit-{timezone.localdate():%Y%m%d}.csv"'
    response.write("﻿")
    writer = csv.writer(response, delimiter=";")
    writer.writerow(["Date", "Membre", "Action", "Objet", "Détails", "Adresse IP", "Navigateur"])
    for log in _filtered(request)[:20000]:
        writer.writerow([timezone.localtime(log.created_at).strftime("%d/%m/%Y %H:%M:%S"), _safe(log.actor_label),
                         log.label, _safe(log.target_label), _safe(log.details), log.ip or "", _safe(log.user_agent)])
    return response


def _safe(value: str) -> str:
    value = str(value or "")
    return "'" + value if value[:1] in ("=", "+", "-", "@") else value
