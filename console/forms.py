from django import forms
from django.contrib.auth import get_user_model

from dossiers.forms import DATE_WIDGET, StyledFormMixin

from .models import Prospect, ProspectActivity

User = get_user_model()


def platform_users():
    return User.objects.filter(role=User.Role.PLATFORM_ADMIN, is_active=True)


class ProspectForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Prospect
        fields = ["name", "priority", "status", "owner", "segment", "zone", "phone", "whatsapp", "email",
                  "website", "decision_maker", "channel", "estimated_dossiers", "next_follow_up", "notes",
                  "lost_reason", "source"]
        widgets = {"next_follow_up": DATE_WIDGET, "notes": forms.Textarea(attrs={"rows": 3}),
                   "source": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owner"].queryset = platform_users()


class ProspectFilterForm(StyledFormMixin, forms.Form):
    q = forms.CharField(label="Recherche", required=False,
                        widget=forms.TextInput(attrs={"placeholder": "Nom, téléphone, courriel, décideur…"}))
    priority = forms.ChoiceField(label="Priorité", required=False, choices=[("", "Toutes les priorités")] + Prospect.Priority.choices)
    status = forms.ChoiceField(label="Étape", required=False, choices=[("", "Toutes les étapes")] + Prospect.Status.choices)
    segment = forms.ChoiceField(label="Segment", required=False)
    owner = forms.ModelChoiceField(label="Commercial", required=False, queryset=User.objects.none(), empty_label="Tous les commerciaux")
    due = forms.BooleanField(label="Relances dues", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        segments = Prospect.objects.exclude(segment="").order_by("segment").values_list("segment", flat=True).distinct()
        self.fields["segment"].choices = [("", "Tous les segments")] + [(s, s) for s in segments]
        self.fields["owner"].queryset = platform_users()


class ActivityForm(StyledFormMixin, forms.Form):
    kind = forms.ChoiceField(label="Type", choices=[c for c in ProspectActivity.Kind.choices if c[0] != "status"])
    summary = forms.CharField(label="Compte rendu", widget=forms.Textarea(attrs={"rows": 3,
                              "placeholder": "Qui avez-vous eu ? Qu'a-t-il dit ? Prochaine étape ?"}))
    next_follow_up = forms.DateField(label="Prochaine relance", required=False, widget=DATE_WIDGET)


class StatusChangeForm(StyledFormMixin, forms.Form):
    status = forms.ChoiceField(label="Étape", choices=Prospect.Status.choices)
    reason = forms.CharField(label="Motif (si perdu / hors cible)", required=False, max_length=255)


class ConvertForm(StyledFormMixin, forms.Form):
    agency_name = forms.CharField(label="Nom de l'agence", max_length=150)
    admin_first_name = forms.CharField(label="Prénom du responsable", max_length=150, required=False)
    admin_last_name = forms.CharField(label="Nom du responsable", max_length=150, required=False)
    admin_email = forms.EmailField(label="Courriel du responsable")
    phone = forms.CharField(label="Téléphone", max_length=30, required=False)


class ImportForm(StyledFormMixin, forms.Form):
    file = forms.FileField(label="Fichier CSV ou Word (.docx)")

    def clean_file(self):
        f = self.cleaned_data["file"]
        if not f.name.lower().endswith((".csv", ".docx")):
            raise forms.ValidationError("Formats acceptés : .csv ou .docx.")
        if f.size > 5 * 1024 * 1024:
            raise forms.ValidationError("Fichier trop volumineux (5 Mo maximum).")
        return f


class AgencyPlanForm(StyledFormMixin, forms.Form):
    ACTIONS = [
        ("extend_trial", "Prolonger l'essai de 14 jours"),
        ("activate_month", "Activer — 1 mois payé"),
        ("activate_year", "Activer — 12 mois payés"),
        ("suspend", "Suspendre"),
        ("reactivate", "Réactiver"),
    ]
    action = forms.ChoiceField(choices=ACTIONS)
