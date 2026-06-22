from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from accounts.models import User
from companies.models import ActivityLog, Company, Task, Team, TeamMembership, TeamMessage
from dashboard.models import OTPVerification


class Command(BaseCommand):
    help = (
        'Permanently wipe all application data (OTP, messages, tasks, teams, '
        'companies, employees). Superusers are preserved unless --wipe-superusers is set.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirm',
            action='store_true',
            dest='confirmed',
            help='Required safety flag — confirms you intend an irreversible global wipe.',
        )
        parser.add_argument(
            '--wipe-superusers',
            action='store_true',
            help='Also delete every superuser account (full auth reset).',
        )
        parser.add_argument(
            '--flush-sessions',
            action='store_true',
            help='Clear all Django session records after the wipe.',
        )

    def handle(self, *args, **options):
        if not options['confirmed']:
            raise CommandError(
                'Refusing to run without --confirm. '
                'This operation permanently deletes application data and cannot be undone.'
            )

        wipe_superusers = options['wipe_superusers']
        flush_sessions = options['flush_sessions']
        vendor = connection.vendor
        summary = {}

        self.stdout.write(self.style.WARNING('Starting nuclear database flush…'))

        with transaction.atomic():
            with connection.cursor() as cursor:
                self._disable_foreign_key_checks(cursor, vendor)
                try:
                    summary.update(self._execute_ordered_wipe(wipe_superusers=wipe_superusers))
                finally:
                    self._enable_foreign_key_checks(cursor, vendor)

            if flush_sessions:
                deleted_sessions, _ = Session.objects.all().delete()
                summary['sessions'] = deleted_sessions

        self._print_summary(summary, wipe_superusers=wipe_superusers, flush_sessions=flush_sessions)
        self.stdout.write(self.style.SUCCESS('Nuclear flush completed successfully.'))

    def _disable_foreign_key_checks(self, cursor, vendor):
        if vendor == 'sqlite':
            cursor.execute('PRAGMA foreign_keys = OFF;')
        elif vendor == 'postgresql':
            cursor.execute('SET CONSTRAINTS ALL DEFERRED;')

    def _enable_foreign_key_checks(self, cursor, vendor):
        if vendor == 'sqlite':
            cursor.execute('PRAGMA foreign_keys = ON;')
        elif vendor == 'postgresql':
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE;')

    def _execute_ordered_wipe(self, *, wipe_superusers):
        summary = {}

        summary['otp_verifications'] = self._hard_delete(OTPVerification)
        summary['team_messages'] = self._hard_delete(TeamMessage)
        summary['tasks'] = self._hard_delete(Task)
        summary['activity_logs'] = self._hard_delete(ActivityLog)
        summary['team_memberships'] = self._hard_delete(TeamMembership)
        self._clear_legacy_team_member_table()
        summary['teams'] = self._hard_delete(Team)
        summary['companies'] = self._hard_delete(Company)
        summary['users'] = self._wipe_users(wipe_superusers=wipe_superusers)

        return summary

    def _hard_delete(self, model):
        deleted_count, _ = model.objects.all().delete()
        return deleted_count

    def _clear_legacy_team_member_table(self):
        table_names = connection.introspection.table_names()
        if 'companies_team_members' not in table_names:
            return 0

        with connection.cursor() as cursor:
            cursor.execute('DELETE FROM companies_team_members;')
            return cursor.rowcount

    def _wipe_users(self, *, wipe_superusers):
        users = User.objects.all()
        if not wipe_superusers:
            users = users.filter(is_superuser=False)

        deleted_total = 0
        for user in users.iterator():
            Team.objects.filter(team_leader_id=user.pk).update(team_leader=None)
            TeamMembership.objects.filter(user_id=user.pk).delete()
            OTPVerification.objects.filter(user_id=user.pk).delete()
            user.groups.clear()
            user.user_permissions.clear()
            user.delete()
            deleted_total += 1

        return deleted_total

    def _print_summary(self, summary, *, wipe_superusers, flush_sessions):
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('Deletion summary'))
        rows = [
            ('OTPVerification', summary.get('otp_verifications', 0)),
            ('TeamMessage', summary.get('team_messages', 0)),
            ('Task', summary.get('tasks', 0)),
            ('ActivityLog', summary.get('activity_logs', 0)),
            ('TeamMembership', summary.get('team_memberships', 0)),
            ('Team', summary.get('teams', 0)),
            ('Company', summary.get('companies', 0)),
            ('User / Employee', summary.get('users', 0)),
        ]
        if flush_sessions:
            rows.append(('Session', summary.get('sessions', 0)))

        for label, count in rows:
            self.stdout.write(f'  {label:<20} {count:>8}')

        preserved = 0 if wipe_superusers else get_user_model().objects.filter(is_superuser=True).count()
        if preserved:
            self.stdout.write('')
            self.stdout.write(self.style.NOTICE(f'Preserved superuser accounts: {preserved}'))
