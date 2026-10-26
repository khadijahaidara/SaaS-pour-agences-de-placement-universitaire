from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from dossiers.services import BusinessRuleError


def exception_handler(exc, context):
    """Les refus de règles métier deviennent des erreurs 400 lisibles."""
    if isinstance(exc, BusinessRuleError):
        return Response({"detail": str(exc), "code": "business_rule"}, status=status.HTTP_400_BAD_REQUEST)
    return drf_exception_handler(exc, context)
