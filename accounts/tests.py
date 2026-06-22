from django.test import TestCase
from django.urls import reverse

from dashboard.models import OTPVerification
from .forms import CompanyRegistrationForm, UserLoginForm
from .models import User
from companies.models import Company, Team, Task, ActivityLog


class CompanyRegistrationTests(TestCase):
    def test_registering_company_creates_company_with_owner(self):
        form = CompanyRegistrationForm(data={
            'username': 'owneruser',
            'email': 'owner@example.com',
            'company_name': 'Acme Labs',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        })

        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()

        self.assertFalse(user.is_active)
        self.assertIsNotNone(user.company)
        self.assertEqual(user.company.name, 'Acme Labs')
        self.assertEqual(user.company.owner, user)

    def test_register_and_login_views_work_with_named_urls(self):
        register_response = self.client.get(reverse('accounts:register'))
        self.assertEqual(register_response.status_code, 200)

        register_result = self.client.post(reverse('accounts:register'), {
            'username': 'newowner',
            'email': 'newowner@example.com',
            'company_name': 'Nova Labs',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        })
        self.assertEqual(register_result.status_code, 302)
        self.assertRedirects(register_result, reverse('accounts:verify_otp'))

        user = User.objects.get(username='newowner')
        signup_otp = OTPVerification.objects.filter(user=user, purpose='signup').latest('created_at')
        verify_result = self.client.post(reverse('accounts:verify_otp'), {
            'otp_code': signup_otp.otp_code,
        })
        self.assertEqual(verify_result.status_code, 302)
        self.assertRedirects(verify_result, reverse('dashboard:dashboard'))
        user.refresh_from_db()
        self.assertTrue(user.is_active)

        self.client.logout()
        login_response = self.client.get(reverse('accounts:login'))
        self.assertEqual(login_response.status_code, 200)

        login_result = self.client.post(reverse('accounts:login'), {
            'username': 'newowner',
            'password': 'StrongPass123!',
        })
        self.assertEqual(login_result.status_code, 302)
        self.assertRedirects(login_result, reverse('accounts:verify_otp'))

        login_otp = OTPVerification.objects.filter(user=user, purpose='login').latest('created_at')
        verify_login_result = self.client.post(reverse('accounts:verify_otp'), {
            'otp_code': login_otp.otp_code,
        })
        self.assertEqual(verify_login_result.status_code, 302)
        self.assertRedirects(verify_login_result, reverse('dashboard:dashboard'))

    def test_login_form_accepts_email_instead_of_username(self):
        user = User.objects.create_user(
            username='emailuser',
            email='emailuser@example.com',
            password='StrongPass123!',
            role='company',
        )

        form = UserLoginForm(data={
            'username': 'emailuser@example.com',
            'password': 'StrongPass123!',
        })

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.get_user(), user)

    def test_company_owner_login_redirects_to_dashboard(self):
        company = Company.objects.create(name='Northwind', owner=self._create_user('owner', 'owner@example.com', role='company'))
        owner = company.owner
        owner.company = company
        owner.save(update_fields=['company'])

        self.client.force_login(owner)
        response = self.client.get(reverse('accounts:login'))

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('dashboard:dashboard'))

    def test_admin_dashboard_shows_only_company_metrics(self):
        owner = self._create_user('owner', 'owner@example.com', role='company')
        company = Company.objects.create(name='Northwind', owner=owner)
        owner.company = company
        owner.save(update_fields=['company'])

        other_company = Company.objects.create(name='Southwind', owner=self._create_user('other_owner', 'other@example.com', role='company'))
        other_user = self._create_user('other_member', 'other_member@example.com', role='member', company=other_company)

        Team.objects.create(name='Alpha Team', company=company, team_leader=owner)
        Team.objects.create(name='Other Team', company=other_company, team_leader=other_user)

        Task.objects.create(company=company, title='Ship onboarding', status='in_progress', priority='high', due_date='2026-06-20')
        Task.objects.create(company=company, title='Close sprint', status='done', priority='medium', due_date='2026-06-18')
        Task.objects.create(company=other_company, title='Ignore me', status='in_progress', priority='low', due_date='2026-06-25')

        ActivityLog.objects.create(company=company, action='task_created', description='Created onboarding task')
        ActivityLog.objects.create(company=company, action='member_joined', description='Joined the workspace')
        ActivityLog.objects.create(company=other_company, action='task_created', description='Should not appear')

        self.client.force_login(owner)
        response = self.client.get(reverse('dashboard:dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '1')
        self.assertEqual(response.context['total_teams'], 1)
        self.assertEqual(response.context['total_employees'], 1)
        self.assertEqual(response.context['active_tasks'], 1)
        self.assertEqual(response.context['completed_tasks'], 1)
        self.assertEqual(len(response.context['recent_activities']), 2)
        self.assertEqual(len(response.context['upcoming_deadlines']), 2)

    def _create_user(self, username, email, role, company=None):
        return User.objects.create_user(username=username, email=email, password='StrongPass123!', role=role, company=company)
