from django import forms
from django.conf import settings

from dossiers.forms import StyledFormMixin

from .delivery import UnsafeURL, validate_url
from .models import EVENTS, WebhookEndpoint


class WebhookForm(StyledFormMixin, forms.ModelForm):
    events = forms.MultipleChoiceField(choices=EVENTS, required=False, widget=forms.CheckboxSelectMultiple,
                                       label="Événements", help_text="Aucun coché : tous les événements.")

    class Meta:
        model = WebhookEndpoint
        fields = ["url", "description", "events"]
        widgets = {"url": forms.URLInput(attrs={"placeholder": "https://exemple.com/webhooks/neuralis"})}

    def clean_url(self):
        url = self.cleaned_data["url"].strip()
        try:
            validate_url(url)
        except UnsafeURL as e:
            raise forms.ValidationError(str(e))
        if not settings.WEBHOOK_ALLOW_PRIVATE and not url.startswith("https://"):
            raise forms.ValidationError("Seules les URL en https:// sont acceptées.")
        return url
