"""Espace « Abonnement » de l'agence."""
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.exceptions import BusinessRuleError
from dossiers.permissions import agency_perm_required

from .models import FEATURES, Invoice, Plan, PlanChangeRequest, Subscription
from .pdf import render_invoice
from .services import get_subscription, request_plan_change, usage


@agency_perm_required("billing.manage")
def overview(request):
    agency = request.user.agency
    sub = get_subscription(agency)
    plans = list(Plan.objects.filter(is_public=True))
    for p in plans:
        p.yearly_saving = int(p.price_monthly * 12 - p.price_yearly)
        p.monthly_equiv = int(p.price_yearly / 12)
    invoices = Invoice.objects.filter(agency=agency).select_related("plan")
    return render(request, "billing/overview.html", {
        "agency": agency, "sub": sub, "plans": plans, "usage": usage(agency), "invoices": invoices,
        "features": FEATURES, "cycles": Subscription.Cycle.choices,
        "pending": PlanChangeRequest.objects.filter(agency=agency, status=PlanChangeRequest.Status.PENDING)
        .select_related("plan").first(),
        "open_invoice": invoices.filter(status=Invoice.Status.ISSUED).first(),
    })


@require_POST
@agency_perm_required("billing.manage")
def request_change(request):
    plan = get_object_or_404(Plan, code=request.POST.get("plan"), is_public=True)
    cycle = request.POST.get("cycle", Subscription.Cycle.MONTHLY)
    if cycle not in Subscription.Cycle.values:
        cycle = Subscription.Cycle.MONTHLY
    try:
        request_plan_change(request.user.agency, user=request.user, plan=plan, cycle=cycle,
                            message=request.POST.get("message", ""))
    except BusinessRuleError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, f"Demande envoyée : formule {plan.name}. L'équipe NEURALIS vous adresse la facture "
                                  "sous 24 h ouvrées ; la formule s'active dès le paiement.")
    return redirect("billing:overview")


@agency_perm_required("billing.manage")
def invoice_pdf(request, pk):
    invoice = get_object_or_404(Invoice.objects.select_related("agency", "plan"), pk=pk, agency=request.user.agency)
    return pdf_response(invoice)


def pdf_response(invoice):
    response = HttpResponse(render_invoice(invoice), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="facture-{invoice.number}.pdf"'
    return response
