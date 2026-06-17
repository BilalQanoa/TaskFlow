from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.core.exceptions import ValidationError

from .models import User
from companies.models import Company


class CompanyRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    company_name = forms.CharField(max_length=255, required=True)

    class Meta:
        model = User
        fields = ('username', 'email', 'company_name')

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise ValidationError("This email is exist, try to use another email")
        return email
    
    def clean_company_name(self):
        company_name = self.cleaned_data.get('company_name')
        if Company.objects.filter(name=company_name).exists():
            raise ValidationError("This company name is used, enter a unique name")
        return company_name

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.role = 'company'

        if commit:
            user.save()
            company = Company.objects.create(
                name=self.cleaned_data['company_name'],
                owner=user,
            )
            user.company = company
            user.save()

        return user


class UserLoginForm(AuthenticationForm):
    username = forms.CharField(
        label='Username or Email Address',
        widget=forms.TextInput(attrs={'autofocus': True})
    )
    password = forms.CharField(widget=forms.PasswordInput)

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get('username')
        password = cleaned_data.get('password')

        if username and password:
            from django.contrib.auth import authenticate
            user = authenticate(request=None, username=username, password=password)
            if user is None:
                raise ValidationError('Please enter a correct username/email and password.')

        return cleaned_data