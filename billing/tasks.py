"""Renouvellements : facture émise automatiquement 7 jours avant la fin de période."""
from datetime import timedelta

from django.utils import timezone

from agencies.models import Agency

from .models import Invoice
from .services import RENEWAL_NOTICE_DAYS, get_subscription, issue_invoice


def renewal_notices(now=None) -> dict:
    today = timezone.localdate(now or timezone.now())
    issued = 0
    agencies = Agency.objects.filter(is_active=True, plan=Agency.Plan.ACTIVE, paid_until__isnull=False,
                                     paid_until__gte=today, paid_until__lte=today + timedelta(days=RENEWAL_NOTICE_DAYS))
    for agency in agencies:
        sub = get_subscription(agency)
        if sub.renewal_notice_sent_for == agency.paid_until:
            continue
        already = Invoice.objects.filter(agency=agency, status__in=[Invoice.Status.ISSUED, Invoice.Status.PAID],
                                         period_start__gt=agency.paid_until).exists()
        if not already:
            issue_invoice(agency, plan=sub.plan, cycle=sub.cycle, notes="Renouvellement automatique")
            issued += 1
        sub.renewal_notice_sent_for = agency.paid_until
        sub.save(update_fields=["renewal_notice_sent_for"])
    return {"factures_renouvellement": issued}
