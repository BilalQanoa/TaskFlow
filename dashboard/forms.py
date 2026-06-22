from django import forms
from django.contrib.auth.forms import PasswordChangeForm

from accounts.models import User
from companies.models import Company


class UserProfileForm(forms.ModelForm):
    full_name = forms.CharField(
        max_length=255,
        required=True,
        label='Full Name',
        widget=forms.TextInput(attrs={
            'class': 'glass-input',
            'placeholder': 'Enter your full name',
            'autocomplete': 'name',
        }),
    )

    class Meta:
        model = User
        fields = ['email', 'job_title']
        labels = {
            'email': 'Corporate Email',
            'job_title': 'Job Title / Position',
        }
        widgets = {
            'email': forms.EmailInput(attrs={
                'class': 'glass-input',
                'placeholder': 'name@company.com',
                'autocomplete': 'email',
            }),
            'job_title': forms.TextInput(attrs={
                'class': 'glass-input',
                'placeholder': 'e.g. Operations Manager',
                'autocomplete': 'organization-title',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['full_name'].initial = self.instance.get_full_name()

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        duplicate = User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise forms.ValidationError('This corporate email is already registered in the system.')
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        full_name = self.cleaned_data['full_name'].strip()
        name_parts = full_name.split()
        user.first_name = name_parts[0] if name_parts else ''
        user.last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''
        if commit:
            user.save()
        return user


class StyledPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        placeholders = {
            'old_password': 'Enter your current password',
            'new_password1': 'Enter a strong new password',
            'new_password2': 'Confirm your new password',
        }
        labels = {
            'old_password': 'Current Password',
            'new_password1': 'New Password',
            'new_password2': 'Confirm New Password',
        }
        for name, field in self.fields.items():
            field.label = labels.get(name, field.label)
            field.widget.attrs.update({
                'class': 'glass-input',
                'placeholder': placeholders.get(name, ''),
                'autocomplete': 'current-password' if name == 'old_password' else 'new-password',
            })


class EmployeeActivationForm(forms.Form):
    password1 = forms.CharField(
        label='Password',
        min_length=8,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control activation-password',
            'placeholder': 'Create a secure password',
            'autocomplete': 'new-password',
        }),
    )
    password2 = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control activation-password',
            'placeholder': 'Confirm your password',
            'autocomplete': 'new-password',
        }),
    )

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError('The passwords you entered do not match.')
        return cleaned_data


class CompanyWorkspaceForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = ['name', 'logo']
        labels = {
            'name': 'Workspace Name',
            'logo': 'Company Logo',
        }
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'glass-input',
                'placeholder': 'Enter workspace name',
            }),
            'logo': forms.ClearableFileInput(attrs={
                'class': 'glass-file-input',
                'accept': 'image/*',
            }),
        }
