from django.test import TestCase
from django.urls import reverse

from .forms import CompanyRegistrationForm, UserLoginForm
from .models import User


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
        self.assertRedirects(register_result, reverse('accounts:profile'))

        login_response = self.client.get(reverse('accounts:login'))
        self.assertEqual(login_response.status_code, 200)

        login_result = self.client.post(reverse('accounts:login'), {
            'username': 'newowner',
            'password': 'StrongPass123!',
        })
        self.assertEqual(login_result.status_code, 302)
        self.assertRedirects(login_result, reverse('accounts:profile'))

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
