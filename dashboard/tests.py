from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from companies.models import Company, Team, TeamMembership


class TeamsListViewTenantIsolationTests(TestCase):
    def setUp(self):
        self.User = get_user_model()

        self.company_a = Company.objects.create(name='Acme', owner=self.User.objects.create_user(
            username='owner-a',
            email='owner-a@example.com',
            password='password123',
            role='company',
        ))
        self.company_b = Company.objects.create(name='Globex', owner=self.User.objects.create_user(
            username='owner-b',
            email='owner-b@example.com',
            password='password123',
            role='company',
        ))

        self.user_a = self.User.objects.create_user(
            username='member-a',
            email='member-a@example.com',
            password='password123',
            role='member',
            company=self.company_a,
        )
        self.user_b = self.User.objects.create_user(
            username='member-b',
            email='member-b@example.com',
            password='password123',
            role='member',
            company=self.company_b,
        )

        self.team_a = Team.objects.create(name='Alpha Team', company=self.company_a, team_leader=self.user_a)
        self.team_b = Team.objects.create(name='Beta Team', company=self.company_b, team_leader=self.user_b)

    def test_only_company_teams_are_visible(self):
        self.client.force_login(self.user_a)
        response = self.client.get(reverse('dashboard:teams'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.team_a.name)
        self.assertNotContains(response, self.team_b.name)

    def test_add_team_member_creates_membership_with_role(self):
        self.client.force_login(self.company_a.owner)
        response = self.client.post(
            reverse('dashboard:add_team_member', args=[self.team_a.pk]),
            {
                'member_name': 'Ada Lovelace',
                'member_email': 'ada@example.com',
                'member_role': 'Backend Engineer',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        membership = TeamMembership.objects.get(team=self.team_a, user__email='ada@example.com')
        self.assertEqual(membership.role, 'Backend Engineer')

    def test_remove_team_member_deletes_membership(self):
        self.client.force_login(self.company_a.owner)
        member = self.User.objects.create_user(
            username='member-c',
            email='member-c@example.com',
            password='password123',
            role='member',
            company=self.company_a,
        )
        membership = TeamMembership.objects.create(team=self.team_a, user=member, role='QA Engineer')

        response = self.client.post(
            reverse('dashboard:remove_team_member', args=[self.team_a.pk, member.pk]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(TeamMembership.objects.filter(pk=membership.pk).exists())

    def test_assign_leader_denies_reassignment_when_leader_exists(self):
        self.client.force_login(self.company_a.owner)
        existing_leader = self.User.objects.create_user(
            username='leader-existing',
            email='leader-existing@example.com',
            password='password123',
            role='member',
            company=self.company_a,
        )
        self.team_a.team_leader = existing_leader
        self.team_a.save(update_fields=['team_leader'])

        response = self.client.post(
            reverse('dashboard:assign_leader', args=[self.team_a.pk]),
            {
                'leader_name': 'Jane Doe',
                'leader_email': 'jane@example.com',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Operation Denied: This team already has an active Team Leader assigned.')
        self.team_a.refresh_from_db()
        self.assertEqual(self.team_a.team_leader, existing_leader)

    def test_delete_team_removes_team_and_shows_success_message(self):
        self.client.force_login(self.company_a.owner)

        response = self.client.post(
            reverse('dashboard:delete_team', args=[self.team_a.pk]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Team.objects.filter(pk=self.team_a.pk).exists())
        self.assertContains(response, 'The team has been successfully dissolved and all associated records deleted.')

    def test_delete_team_clears_legacy_team_member_rows_before_deleting(self):
        self.client.force_login(self.company_a.owner)

        with connection.cursor() as cursor:
            cursor.execute('INSERT INTO companies_team_members (team_id, user_id) VALUES (?, ?)', [self.team_a.pk, self.user_a.pk])

        response = self.client.post(
            reverse('dashboard:delete_team', args=[self.team_a.pk]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Team.objects.filter(pk=self.team_a.pk).exists())
