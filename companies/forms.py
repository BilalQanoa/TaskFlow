from django import forms

from accounts.models import User


class TeamCreateForm(forms.Form):
    name = forms.CharField(
        max_length=255,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    leader_email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control'}),
    )
    member_emails = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 4, 'class': 'form-control', 'placeholder': 'Enter emails separated by commas'}),
        help_text='Enter one or more member emails separated by commas.',
    )

    def __init__(self, *args, **kwargs):
        self.owner = kwargs.pop('owner', None)
        super().__init__(*args, **kwargs)

    def clean_leader_email(self):
        email = self.cleaned_data.get('leader_email', '').strip().lower()
        if not email:
            return ''

        user = User.objects.filter(email__iexact=email).first()
        if not user:
            raise forms.ValidationError('No user was found with that email.')

        company = self.owner.company if self.owner else None
        if user.company_id != getattr(company, 'id', None):
            raise forms.ValidationError('The team leader must belong to your company.')

        return email

    def clean_member_emails(self):
        raw_value = self.cleaned_data.get('member_emails', '')
        emails = [email.strip().lower() for email in raw_value.split(',') if email.strip()]
        company = self.owner.company if self.owner else None

        if not emails:
            return []

        for email in emails:
            user = User.objects.filter(email__iexact=email).first()
            if not user:
                raise forms.ValidationError(f'No user was found for member email: {email}')
            if user.company_id != getattr(company, 'id', None):
                raise forms.ValidationError(f'The member {email} must belong to your company.')

        return emails

    def save(self, owner=None):
        from companies.models import Team

        owner = owner or self.owner
        company = owner.company if owner else None
        if not company:
            raise ValueError('The owner must belong to a company.')

        leader_email = self.cleaned_data['leader_email'].strip().lower()
        member_emails = self.cleaned_data.get('member_emails', [])

        leader = User.objects.get(email__iexact=leader_email)
        members = [User.objects.get(email__iexact=email) for email in member_emails]

        team = Team.objects.create(
            name=self.cleaned_data['name'],
            company=company,
            team_leader=leader,
        )
        team.members.add(leader, *members)
        return team


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