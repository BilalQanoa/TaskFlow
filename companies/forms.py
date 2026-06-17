from django import forms

from accounts.models import User


class InviteUserForm(forms.ModelForm):
    role = forms.ChoiceField(choices=[('team_leader', 'Team Leader'), ('member', 'Member')])

    class Meta:
        model = User
        fields = ('username', 'email', 'role')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_unusable_password()
        if commit:
            user.save()
        return user