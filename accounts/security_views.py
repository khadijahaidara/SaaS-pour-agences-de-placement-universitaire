"""Écrans de sécurité du compte : second facteur à la connexion, 2FA, sessions."""
import pyotp
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from audit.models import AuditLog
from audit.services import record

from . import security
from .models import RecoveryCode, TOTPDevice, UserSession
from .views import layout_for


def login_2fa(request):
    user, data = security.pending_user(request)
    if user is None:
        messages.error(request, "Session de connexion expirée. Saisissez à nouveau votre mot de passe.")
        return redirect("accounts:login")
    error = None
    if request.method == "POST":
        method = security.verify_second_factor(user, request.POST.get("code", ""))
        if method:
            request.session.pop(security.PENDING_KEY, None)
            login(request, user, backend=data["backend"])
            if method == "recovery":
                record("auth.recovery_used", agency=user.agency, actor=user, request=request)
                left = RecoveryCode.objects.filter(user=user, used_at__isnull=True).count()
                messages.warning(request, f"Code de secours utilisé. Il vous en reste {left}. "
                                          "Pensez à en générer de nouveaux dans Sécurité du compte.")
            nxt = data.get("next") or "/"
            if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
                nxt = "/"
            return redirect(nxt)
        data["attempts"] = data.get("attempts", 0) + 1
        request.session[security.PENDING_KEY] = data
        record("auth.2fa_failed", agency=user.agency, target=user, request=request)
        if data["attempts"] >= security.MAX_2FA_ATTEMPTS:
            request.session.pop(security.PENDING_KEY, None)
            security.register_failure(request, user.email)
            messages.error(request, "Trop de codes erronés. Reconnectez-vous.")
            return redirect("accounts:login")
        error = "Code incorrect ou expiré. Vérifiez l'heure de votre téléphone et réessayez."
    return render(request, "accounts/login_2fa.html", {"error": error, "pending_email": user.email,
                                                       "login_agency": getattr(request, "tenant", None)})


@login_required
def security_page(request):
    user = request.user
    device = TOTPDevice.objects.filter(user=user).first()
    setup = None
    if device and not device.confirmed_at:
        setup = {"secret": device.secret, "qr": security.qr_svg(device.provisioning_uri()),
                 "secret_groups": " ".join(device.secret[i:i + 4] for i in range(0, len(device.secret), 4))}
    sessions = list(UserSession.objects.filter(user=user))
    for s in sessions:
        s.current = s.session_key == request.session.session_key
    activity = AuditLog.objects.filter(actor=user, action__startswith="auth.")[:10]
    failed = AuditLog.objects.filter(target_type="user", target_id=str(user.pk), action="auth.login_failed")[:5]
    return render(request, "accounts/security.html", {
        "layout": layout_for(user), "device": device, "setup": setup, "sessions": sessions,
        "activity": activity, "failed": failed,
        "recovery_left": RecoveryCode.objects.filter(user=user, used_at__isnull=True).count(),
        "new_codes": request.session.pop("new_recovery_codes", None),
        "mandatory": security.requires_2fa_setup(user),
    })


@require_POST
@login_required
def totp_start(request):
    device, _ = TOTPDevice.objects.get_or_create(user=request.user, defaults={"secret": pyotp.random_base32()})
    if device.confirmed_at:
        messages.info(request, "La double authentification est déjà active.")
    else:
        device.secret = pyotp.random_base32()
        device.last_used_step = 0
        device.save(update_fields=["secret", "last_used_step"])
    return redirect("accounts:security")


@require_POST
@login_required
def totp_confirm(request):
    device = get_object_or_404(TOTPDevice, user=request.user, confirmed_at__isnull=True)
    if not device.verify(request.POST.get("code", "")):
        messages.error(request, "Code incorrect. Scannez à nouveau le QR code et saisissez le code affiché.")
        return redirect("accounts:security")
    device.confirmed_at = timezone.now()
    device.save(update_fields=["confirmed_at"])
    request.session["new_recovery_codes"] = RecoveryCode.regenerate(request.user)
    record("auth.2fa_enabled", agency=request.user.agency, actor=request.user, target=request.user)
    messages.success(request, "Double authentification activée. Conservez vos codes de secours en lieu sûr.")
    return redirect("accounts:security")


@require_POST
@login_required
def totp_disable(request):
    user = request.user
    if not user.check_password(request.POST.get("password", "")):
        messages.error(request, "Mot de passe incorrect.")
        return redirect("accounts:security")
    if user.has_2fa and not security.verify_second_factor(user, request.POST.get("code", "")):
        messages.error(request, "Code de vérification incorrect.")
        return redirect("accounts:security")
    if user.is_agency_staff and user.agency and user.agency.require_2fa:
        messages.error(request, "Votre agence impose la double authentification : elle ne peut pas être désactivée.")
        return redirect("accounts:security")
    TOTPDevice.objects.filter(user=user).delete()
    RecoveryCode.objects.filter(user=user).delete()
    record("auth.2fa_disabled", agency=user.agency, actor=user, target=user)
    messages.success(request, "Double authentification désactivée.")
    return redirect("accounts:security")


@require_POST
@login_required
def recovery_regenerate(request):
    if not request.user.has_2fa:
        return redirect("accounts:security")
    if not security.verify_second_factor(request.user, request.POST.get("code", "")):
        messages.error(request, "Code de vérification incorrect.")
        return redirect("accounts:security")
    request.session["new_recovery_codes"] = RecoveryCode.regenerate(request.user)
    messages.success(request, "Nouveaux codes de secours générés : les anciens ne fonctionnent plus.")
    return redirect("accounts:security")


@require_POST
@login_required
def session_revoke(request, pk):
    session = get_object_or_404(UserSession, pk=pk, user=request.user)
    if session.session_key == request.session.session_key:
        messages.error(request, "Pour fermer cette session, utilisez « Se déconnecter ».")
    else:
        session.revoke()
        record("auth.session_revoked", agency=request.user.agency, actor=request.user,
               metadata={"appareil": session.device_label})
        messages.success(request, f"Session « {session.device_label} » déconnectée.")
    return redirect("accounts:security")


@require_POST
@login_required
def sessions_revoke_others(request):
    others = UserSession.objects.filter(user=request.user).exclude(session_key=request.session.session_key)
    n = 0
    for s in others:
        s.revoke()
        n += 1
    record("auth.session_revoked", agency=request.user.agency, actor=request.user, metadata={"sessions": n})
    messages.success(request, f"{n} autre{'s' if n > 1 else ''} session{'s' if n > 1 else ''} déconnectée{'s' if n > 1 else ''}.")
    return redirect("accounts:security")
