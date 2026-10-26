"""Écriture du journal d'audit. Ne fait jamais échouer l'action journalisée."""
import logging

from . import context
from .models import AuditLog

logger = logging.getLogger(__name__)


def record(action: str, *, agency=None, actor=None, target=None, metadata=None, request=None) -> AuditLog | None:
    request = request or context.get_request()
    if actor is None and request is not None and getattr(request, "user", None) is not None \
            and request.user.is_authenticated:
        actor = request.user
    if agency is None and actor is not None:
        agency = getattr(actor, "agency", None)
    try:
        return AuditLog.objects.create(
            agency=agency,
            actor=actor if actor is not None and getattr(actor, "pk", None) else None,
            actor_label=(str(actor) if actor is not None else "Système")[:200],
            action=action,
            target_type=target._meta.model_name if target is not None else "",
            target_id=str(target.pk) if target is not None else "",
            target_label=str(target)[:200] if target is not None else "",
            ip=context.client_ip(request) if request is not None else None,
            user_agent=(request.META.get("HTTP_USER_AGENT", "")[:255] if request is not None else ""),
            metadata={k: v for k, v in (metadata or {}).items()},
        )
    except Exception:  # pragma: no cover - le journal ne doit pas bloquer le métier
        logger.exception("Écriture du journal d'audit impossible (%s)", action)
        return None
