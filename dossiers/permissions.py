"""Contrôles d'accès communs.

Principe : on ne fait jamais `Dossier.objects.get(pk=...)` dans une vue ;
on passe par `Dossier.objects.for_user(user)` pour que l'isolation entre
agences et entre étudiants soit appliquée partout de la même façon.
Un objet hors périmètre renvoie 404 (on ne révèle pas son existence).

Les actions sensibles sont protégées par des permissions fines
(`agency_perm_required("payments.cancel")`), définies dans accounts/rbac.py.
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from .models import Dossier


def agency_staff_required(view):
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_agency_staff:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


def agency_perm_required(*codes):
    """Membre de l'équipe disposant de toutes les permissions indiquées."""

    def decorator(view):
        @login_required
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not user.is_agency_staff or not all(user.has_agency_perm(c) for c in codes):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


def agency_admin_required(view):
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_agency_admin:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


def student_required(view):
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_student:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


def get_dossier_for(user, pk, *, for_update=False) -> Dossier:
    qs = Dossier.objects.for_user(user).select_related("agency", "student", "counselor", "workflow")
    if for_update:
        qs = qs.select_for_update()
    return get_object_or_404(qs, pk=pk)
