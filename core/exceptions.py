class BusinessRuleError(Exception):
    """Action refusée par une règle métier ; le message est affichable tel quel."""


class QuotaExceeded(BusinessRuleError):
    """Limite de la formule d'abonnement atteinte."""
