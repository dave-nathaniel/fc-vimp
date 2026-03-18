"""
Management command to generate authentication tokens for API testing.

Usage:
    python manage.py get_auth_token --username <username>
    python manage.py get_auth_token --email <email>
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from datetime import datetime

User = get_user_model()


class Command(BaseCommand):
    help = 'Generate JWT authentication token for API testing'

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            type=str,
            help='Username of the user',
        )
        parser.add_argument(
            '--email',
            type=str,
            help='Email of the user',
        )
        parser.add_argument(
            '--list-users',
            action='store_true',
            help='List all available users',
        )

    def handle(self, *args, **options):
        # List users if requested
        if options['list_users']:
            self.list_users()
            return

        username = options.get('username')
        email = options.get('email')

        if not username and not email:
            self.stdout.write(self.style.ERROR(
                'Please provide either --username or --email'
            ))
            self.stdout.write('\nUsage:')
            self.stdout.write('  python manage.py get_auth_token --username <username>')
            self.stdout.write('  python manage.py get_auth_token --email <email>')
            self.stdout.write('  python manage.py get_auth_token --list-users')
            return

        # Find user
        try:
            if username:
                user = User.objects.get(username=username)
            else:
                user = User.objects.get(email=email)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(
                f'User not found with {"username" if username else "email"}: '
                f'{username or email}'
            ))
            self.stdout.write('\nAvailable users:')
            self.list_users()
            return

        # Generate tokens
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)
        refresh_token = str(refresh)

        # Display tokens
        self.stdout.write(self.style.MIGRATE_HEADING('\n' + '='*80))
        self.stdout.write(self.style.MIGRATE_HEADING('JWT Authentication Tokens'))
        self.stdout.write(self.style.MIGRATE_HEADING('='*80))

        self.stdout.write(f'\n{self.style.WARNING("User Information:")}')
        self.stdout.write(f'  Username:    {user.username}')
        self.stdout.write(f'  Email:       {user.email}')
        self.stdout.write(f'  Name:        {user.get_full_name()}')
        self.stdout.write(f'  Active:      {user.is_active}')
        self.stdout.write(f'  Staff:       {user.is_staff}')
        self.stdout.write(f'  Superuser:   {user.is_superuser}')

        self.stdout.write(f'\n{self.style.WARNING("Access Token (use this for API calls):")}')
        self.stdout.write(f'{self.style.SUCCESS(access_token)}')

        self.stdout.write(f'\n{self.style.WARNING("Refresh Token:")}')
        self.stdout.write(refresh_token)

        # Decode token info
        from rest_framework_simplejwt.tokens import AccessToken
        token_obj = AccessToken(access_token)

        self.stdout.write(f'\n{self.style.WARNING("Token Details:")}')
        self.stdout.write(f'  User ID:     {token_obj["user_id"]}')
        self.stdout.write(f'  Expires:     {datetime.fromtimestamp(token_obj["exp"])}')
        self.stdout.write(f'  Issued:      {datetime.fromtimestamp(token_obj["iat"])}')

        self.stdout.write(f'\n{self.style.WARNING("Usage in curl:")}')
        self.stdout.write(
            f'curl -H "Authorization: Bearer {access_token}" \\\n'
            f'  http://localhost:8000/imprest/v1/items/'
        )

        self.stdout.write(f'\n{self.style.WARNING("Usage in Postman:")}')
        self.stdout.write('1. Go to Authorization tab')
        self.stdout.write('2. Select Type: Bearer Token')
        self.stdout.write(f'3. Paste token: {access_token[:20]}...')

        self.stdout.write(f'\n{self.style.WARNING("Set as Postman Environment Variable:")}')
        self.stdout.write(f'  Variable: jwt_token')
        self.stdout.write(f'  Value:    {access_token}')

        self.stdout.write('\n' + '='*80 + '\n')

    def list_users(self):
        """List all available users"""
        users = User.objects.all().order_by('username')

        if not users.exists():
            self.stdout.write(self.style.ERROR('No users found in database'))
            return

        self.stdout.write(self.style.MIGRATE_HEADING('\nAvailable Users:'))
        self.stdout.write('-'*80)
        self.stdout.write(f'{"Username":<20} {"Email":<30} {"Name":<25} {"Active":<8}')
        self.stdout.write('-'*80)

        for user in users:
            active = self.style.SUCCESS('Yes') if user.is_active else self.style.ERROR('No')
            self.stdout.write(
                f'{user.username:<20} {user.email:<30} '
                f'{user.get_full_name():<25} {active}'
            )

        self.stdout.write('-'*80)
        self.stdout.write(f'Total: {users.count()} users\n')
