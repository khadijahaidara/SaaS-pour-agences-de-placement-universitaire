from django.utils import timezone
from rest_framework import authentication, exceptions

from .models import ApiKey


class ApiKeyAuthentication(authentication.BaseAuthentication):
    """En-tête : « Authorization: Api-Key nm_xxxxxxxx_… ».

    L'utilisateur associé est le responsable qui a créé la clé (il apparaît comme auteur
    des actions dans l'historique) ; le périmètre est toute l'agence de la clé.
    """

    keyword = "Api-Key"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode("latin-1")
        if not header:
            return None
        parts = header.split()
        if len(parts) != 2 or parts[0] != self.keyword:
            return None
        key = ApiKey.from_raw(parts[1])
        if key is None:
            raise exceptions.AuthenticationFailed("Clé API invalide ou révoquée.")
        user = key.created_by
        if not user.is_active or user.agency_id != key.agency_id:
            raise exceptions.AuthenticationFailed("Le compte qui a créé cette clé n'est plus actif.")
        if key.last_used_at is None or (timezone.now() - key.last_used_at).total_seconds() > 60:
            ApiKey.objects.filter(pk=key.pk).update(last_used_at=timezone.now())
        return user, key

    def authenticate_header(self, request):
        return self.keyword
