from django.test import TestCase

from accounts.models import User
from companies.forms import TeamCreateForm
from companies.models import Company, Team


class TeamCreateFormTests(TestCase):
    def setUp(self):
        self.owner_a = self._create_user('owner', 'owner@example.com', role='company')
        self.company_a = Company.objects.create(name='Alpha Labs', owner=self.owner_a)
        self.owner_a.company = self.company_a
        self.owner_a.save(update_fields=['company'])

        self.owner_b = self._create_user('other_owner', 'other@example.com', role='company')
        self.company_b = Company.objects.create(name='Beta Labs', owner=self.owner_b)
        self.owner_b.company = self.company_b
        self.owner_b.save(update_fields=['company'])

        self.same_company_user = self._create_user('member', 'member@example.com', role='member', company=self.company_a)
        self.other_company_user = self._create_user('foreign', 'foreign@example.com', role='member', company=self.company_b)

    def _create_user(self, username, email, role, company=None):
        return User.objects.create_user(username=username, email=email, password='secret123', role=role, company=company)

    def test_form_rejects_leader_from_other_company(self):
        form = TeamCreateForm(
            data={
                'name': 'Platform Team',
                'leader_email': 'foreign@example.com',
                'member_emails': 'member@example.com',
            },
            owner=self.company_a.owner,
        )

        self.assertFalse(form.is_valid())
        self.assertIn('leader_email', form.errors)

    def test_form_creates_team_for_same_company_users(self):
        form = TeamCreateForm(
            data={
                'name': 'Design Team',
                'leader_email': 'member@example.com',
                'member_emails': 'member@example.com, owner@example.com',
            },
            owner=self.company_a.owner,
        )

        self.assertTrue(form.is_valid(), form.errors)
        team = form.save(owner=self.company_a.owner)

        self.assertEqual(team.company, self.company_a)
        self.assertEqual(team.team_leader, self.same_company_user)
        self.assertEqual(team.members.count(), 2)
        self.assertTrue(team.members.filter(pk=self.same_company_user.pk).exists())
        self.assertTrue(team.members.filter(pk=self.company_a.owner.pk).exists())
