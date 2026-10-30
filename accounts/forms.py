from django import forms
from django.contrib.auth.forms import PasswordChangeForm

from dossiers.forms import StyledFormMixin

from .models import User


class ProfileForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "phone"]
        widgets = {"phone": forms.TextInput(attrs={"placeholder": "+223 …", "autocomplete": "tel"})}


class NotificationPrefsForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["notify_email", "daily_digest"]


class StyledPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs.update({"class": "input"})
        self.fields["new_password1"].help_text = (
            "8 caractères minimum, pas uniquement des chiffres, et différent de votre nom ou courriel."
        )
        self.fields["new_password1"].widget.attrs["data-strength"] = "1"
        self.fields["new_password2"].help_text = ""


class DisplayPrefsForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["ui_theme", "ui_density"]
        widgets = {"ui_theme": forms.RadioSelect, "ui_density": forms.RadioSelect}
