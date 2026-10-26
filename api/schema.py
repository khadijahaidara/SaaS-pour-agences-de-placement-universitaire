"""Déclare l'authentification par clé API dans la documentation OpenAPI (bouton « Authorize »)."""
from drf_spectacular.extensions import OpenApiAuthenticationExtension


class ApiKeyScheme(OpenApiAuthenticationExtension):
    target_class = "api.authentication.ApiKeyAuthentication"
    name = "ApiKey"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": "Saisissez : Api-Key nm_xxxxxxxx_…",
        }
