from django.db import models


class Agency(models.Model):
    """Une agence cliente du SaaS (locataire). Toutes les données métier y sont rattachées."""

    name = models.CharField("nom", max_length=150)
    slug = models.SlugField(unique=True)
    city = models.CharField("ville", max_length=100, default="Bamako")
    country = models.CharField("pays", max_length=100, default="Mali")
    phone = models.CharField("téléphone", max_length=30, blank=True)
    email = models.EmailField("courriel de contact", blank=True)
    currency = models.CharField("devise", max_length=10, default="FCFA")
    is_active = models.BooleanField("active", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "agence"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
