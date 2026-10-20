from django import forms

from dossiers.forms import StyledFormMixin

from .models import User


class ProfileForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "phone"]
