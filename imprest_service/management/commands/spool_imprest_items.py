"""
Management command to spool G/L Account (Imprest Items) from SAP ByD.

Now working with FINGLACCT data source using SAP_COMM_USER credentials.

G/L Account Types (C_GlacctTc):
- COSEXP: Cost/Expense accounts (for imprest/expense items)
- CASH: Cash/Bank accounts
"""

import os
import json
import requests
from requests.auth import HTTPBasicAuth
from django.core.management.base import BaseCommand
from pathlib import Path
from dotenv import load_dotenv

dotenv_path = os.path.join(Path(__file__).resolve().parent.parent.parent.parent, '.env')
load_dotenv(dotenv_path)


class Command(BaseCommand):
    help = 'Spool G/L Account (Imprest Items) from SAP ByD Analytics OData'

    def __init__(self):
        super().__init__()
        self.sap_url = os.getenv('SAP_URL')

        # Primary credentials (SAP_USER)
        self.sap_user = os.getenv('SAP_USER')
        self.sap_pass = os.getenv('SAP_PASS')

        # Communication arrangement credentials (SAP_COMM_USER)
        self.sap_comm_user = os.getenv('SAP_COMM_USER')
        self.sap_comm_pass = os.getenv('SAP_COMM_PASS')

        # Analytics OData base paths
        self.analytics_base = f"{self.sap_url}/sap/byd/odata/analytics/ds"
        self.custom_base = f"{self.sap_url}/sap/byd/odata/cust/v1"

    def get_auth(self, use_comm_user=False):
        """Get authentication based on user preference"""
        if use_comm_user:
            return HTTPBasicAuth(self.sap_comm_user, self.sap_comm_pass)
        return HTTPBasicAuth(self.sap_user, self.sap_pass)

    def make_request(self, url, use_comm_user=False, timeout=30):
        """Make a GET request with proper headers"""
        auth = self.get_auth(use_comm_user)
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }

        try:
            response = requests.get(url, auth=auth, headers=headers, timeout=timeout)
            return response
        except requests.exceptions.Timeout:
            self.stdout.write(self.style.ERROR(f"Request timed out after {timeout}s"))
            return None
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Request error: {str(e)}"))
            return None

    def display_response(self, response, url):
        """Display response details"""
        if response is None:
            return

        self.stdout.write(f"\nURL: {url}")
        self.stdout.write(f"Status: {response.status_code}")
        self.stdout.write(f"Headers: {dict(response.headers)}")

        if response.status_code == 200:
            self.stdout.write(self.style.SUCCESS("\n--- SUCCESS ---"))
            try:
                data = response.json()
                # Pretty print the JSON
                self.stdout.write(json.dumps(data, indent=2)[:5000])  # Limit output

                # Count results if available
                if 'd' in data:
                    if 'results' in data['d']:
                        count = len(data['d']['results'])
                        self.stdout.write(self.style.SUCCESS(f"\nFound {count} records"))
                    elif isinstance(data['d'], list):
                        self.stdout.write(self.style.SUCCESS(f"\nFound {len(data['d'])} records"))
            except json.JSONDecodeError:
                self.stdout.write(f"Response (not JSON):\n{response.text[:2000]}")
        else:
            self.stdout.write(self.style.ERROR(f"\n--- FAILED (Status {response.status_code}) ---"))
            self.stdout.write(f"Response:\n{response.text[:2000]}")

    def test_transactional_odata(self):
        """Test that transactional OData works (baseline test)"""
        self.stdout.write(self.style.WARNING("\n=== Testing Transactional OData (Baseline) ==="))
        url = f"{self.custom_base}/khpurchaseorder/PurchaseOrderCollection?$format=json&$top=1"
        response = self.make_request(url)
        self.display_response(response, url)
        return response and response.status_code == 200

    def test_exposed_analytics(self, use_comm_user=False):
        """Test FINGLAU04 (Financial Statements) - the EXPOSED data source"""
        cred_type = "COMM_USER" if use_comm_user else "SAP_USER"
        self.stdout.write(self.style.WARNING(f"\n=== Testing FINGLAU04 (EXPOSED) with {cred_type} ==="))

        # Try the exposed Financial Statements data source
        url = f"{self.analytics_base}/Finglau04.svc/Finglau04?$format=json&$top=5"
        response = self.make_request(url, use_comm_user=use_comm_user)
        self.display_response(response, url)
        return response and response.status_code == 200

    def test_finglacct(self, use_comm_user=True):
        """Test FINGLACCT (G/L Account)"""
        cred_type = "COMM_USER" if use_comm_user else "SAP_USER"
        self.stdout.write(self.style.WARNING(f"\n=== Testing FINGLACCT (G/L Account) with {cred_type} ==="))

        url = f"{self.analytics_base}/Finglacct.svc/Finglacct?$format=json&$top=5&$select=C_Glacct,T_Description,C_GlacctTc"
        response = self.make_request(url, use_comm_user=use_comm_user)

        if response and response.status_code == 200:
            self.stdout.write(self.style.SUCCESS(f"\n✓ Connection successful!"))
            try:
                data = response.json()
                results = data.get('d', {}).get('results', [])
                self.stdout.write(f"\nSample data (showing {len(results)} records):")
                self.stdout.write("-" * 60)
                for item in results:
                    gl_acct = item.get('C_Glacct', 'N/A')
                    desc = item.get('T_Description', 'N/A')
                    acct_type = item.get('C_GlacctTc', 'N/A')
                    self.stdout.write(f"{gl_acct} | {acct_type} | {desc}")
                self.stdout.write("-" * 60)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error parsing: {e}"))
        elif response and response.status_code == 404:
            self.stdout.write(self.style.ERROR("\n✗ FINGLACCT is NOT EXPOSED"))
        else:
            self.stdout.write(self.style.ERROR(f"\n✗ Failed: {response.status_code if response else 'No response'}"))

        return response and response.status_code == 200

    def test_finglau02(self, use_comm_user=False):
        """Test FINGLAU02 - alternative G/L Account data source"""
        cred_type = "COMM_USER" if use_comm_user else "SAP_USER"
        self.stdout.write(self.style.WARNING(f"\n=== Testing FINGLAU02 with {cred_type} ==="))

        url = f"{self.analytics_base}/Finglau02.svc/Finglau02?$format=json&$top=5"
        response = self.make_request(url, use_comm_user=use_comm_user)
        self.display_response(response, url)
        return response and response.status_code == 200

    def test_metadata(self, data_source, use_comm_user=False):
        """Test fetching $metadata for a data source"""
        cred_type = "COMM_USER" if use_comm_user else "SAP_USER"
        self.stdout.write(self.style.WARNING(f"\n=== Testing {data_source} $metadata with {cred_type} ==="))

        url = f"{self.analytics_base}/{data_source}.svc/$metadata"
        response = self.make_request(url, use_comm_user=use_comm_user)

        if response:
            self.stdout.write(f"\nURL: {url}")
            self.stdout.write(f"Status: {response.status_code}")
            if response.status_code == 200:
                self.stdout.write(self.style.SUCCESS("\n--- METADATA AVAILABLE ---"))
                # Show first 3000 chars of XML
                self.stdout.write(response.text[:3000])
            else:
                self.stdout.write(self.style.ERROR(f"--- FAILED ---\n{response.text[:1000]}"))
        return response and response.status_code == 200

    def fetch_gl_accounts(self, account_type=None, use_comm_user=True):
        """
        Fetch G/L Accounts from FINGLACCT

        Args:
            account_type: Filter by C_GlacctTc (COSEXP, CASH, etc.)
            use_comm_user: Use COMM_USER credentials (default True)
        """
        cred_type = "COMM_USER" if use_comm_user else "SAP_USER"
        filter_label = f" (Type: {account_type})" if account_type else " (All)"
        self.stdout.write(self.style.WARNING(f"\n=== Fetching G/L Accounts{filter_label} with {cred_type} ==="))

        # Build URL with optional filter
        url = f"{self.analytics_base}/Finglacct.svc/Finglacct?$format=json&$select=C_Glacct,T_Description,C_GlacctTc,C_Chofacct"

        if account_type:
            url += f"&$filter=C_GlacctTc eq '{account_type}'"

        response = self.make_request(url, use_comm_user=use_comm_user, timeout=60)

        if response and response.status_code == 200:
            try:
                data = response.json()
                results = data.get('d', {}).get('results', [])

                self.stdout.write(self.style.SUCCESS(f"\n✓ Fetched {len(results)} G/L Accounts"))
                self.stdout.write("-" * 80)

                # Display results in tabular format
                self.stdout.write(f"{'GL Account':<15} {'Type':<10} {'Description':<50}")
                self.stdout.write("-" * 80)

                for item in results:
                    gl_account = item.get('C_Glacct', 'N/A')
                    description = item.get('T_Description', 'N/A')
                    acct_type = item.get('C_GlacctTc', 'N/A')

                    # Truncate description if too long
                    if len(description) > 47:
                        description = description[:47] + "..."

                    self.stdout.write(f"{gl_account:<15} {acct_type:<10} {description:<50}")

                self.stdout.write("-" * 80)
                self.stdout.write(self.style.SUCCESS(f"Total: {len(results)} accounts\n"))

                return results
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error parsing response: {e}"))
        else:
            self.stdout.write(self.style.ERROR("Failed to fetch G/L Accounts."))

        return None

    def list_available_datasources(self, use_comm_user=False):
        """Try to list available data sources"""
        cred_type = "COMM_USER" if use_comm_user else "SAP_USER"
        self.stdout.write(self.style.WARNING(f"\n=== Listing Analytics Data Sources with {cred_type} ==="))

        # Try service document
        url = f"{self.analytics_base}/"
        response = self.make_request(url, use_comm_user=use_comm_user)
        self.display_response(response, url)
        return response and response.status_code == 200

    def get_auth_token(self):
        """Generate JWT token for API testing"""
        try:
            from django.contrib.auth import get_user_model
            from rest_framework_simplejwt.tokens import RefreshToken

            User = get_user_model()

            # List users
            users = User.objects.filter(is_active=True).order_by('username')
            if not users.exists():
                self.stdout.write(self.style.ERROR("No active users found"))
                return

            self.stdout.write(self.style.WARNING("\n=== Available Users ==="))
            for idx, user in enumerate(users, 1):
                self.stdout.write(f"{idx}. {user.username} ({user.email}) - {user.get_full_name()}")

            choice = input("\nSelect user number (or Enter to cancel): ").strip()
            if not choice:
                return

            try:
                user_idx = int(choice) - 1
                user = users[user_idx]
            except (ValueError, IndexError):
                self.stdout.write(self.style.ERROR("Invalid selection"))
                return

            # Generate token
            refresh = RefreshToken.for_user(user)
            access_token = str(refresh.access_token)

            self.stdout.write(self.style.SUCCESS(f"\n✓ Token generated for {user.username}"))
            self.stdout.write("-" * 80)
            self.stdout.write(self.style.WARNING("Access Token (copy this):"))
            self.stdout.write(self.style.SUCCESS(access_token))
            self.stdout.write("-" * 80)
            self.stdout.write("\nUse in curl:")
            self.stdout.write(f'curl -H "Authorization: Bearer {access_token}" \\')
            self.stdout.write('  http://localhost:8000/imprest/v1/items/')
            self.stdout.write("\nUse in Postman:")
            self.stdout.write("  Authorization > Type: Bearer Token")
            self.stdout.write(f"  Token: {access_token[:30]}...")

        except ImportError as e:
            self.stdout.write(self.style.ERROR(f"Error: {e}"))
            self.stdout.write("Make sure rest_framework_simplejwt is installed")

    def run_all_tests(self):
        """Run all connectivity tests"""
        self.stdout.write(self.style.MIGRATE_HEADING("\n" + "="*60))
        self.stdout.write(self.style.MIGRATE_HEADING("RUNNING ALL CONNECTIVITY TESTS"))
        self.stdout.write(self.style.MIGRATE_HEADING("="*60))

        results = {
            'transactional': self.test_transactional_odata(),
            'finglau04_sap_user': self.test_exposed_analytics(use_comm_user=False),
            'finglau04_comm_user': self.test_exposed_analytics(use_comm_user=True),
            'finglacct_sap_user': self.test_finglacct(use_comm_user=False),
            'finglacct_comm_user': self.test_finglacct(use_comm_user=True),
        }

        self.stdout.write(self.style.MIGRATE_HEADING("\n" + "="*60))
        self.stdout.write(self.style.MIGRATE_HEADING("TEST RESULTS SUMMARY"))
        self.stdout.write(self.style.MIGRATE_HEADING("="*60))

        for test, passed in results.items():
            status = self.style.SUCCESS("PASS") if passed else self.style.ERROR("FAIL")
            self.stdout.write(f"{test}: {status}")

        return results

    def show_menu(self):
        """Display the interactive menu"""
        self.stdout.write(self.style.MIGRATE_HEADING("\n" + "="*80))
        self.stdout.write(self.style.MIGRATE_HEADING("SAP ByD G/L Accounts Spooler (Imprest & Bank Accounts)"))
        self.stdout.write(self.style.MIGRATE_HEADING("="*80))
        self.stdout.write(f"\nSAP URL: {self.sap_url}")
        self.stdout.write(f"Using: {self.sap_comm_user} (COMM_USER)")
        self.stdout.write("\n" + "-"*80)

        self.stdout.write(self.style.WARNING("\n📊 FETCH G/L ACCOUNTS (FINGLACCT):"))
        self.stdout.write("  1. Fetch ALL G/L Accounts")
        self.stdout.write("  2. Fetch EXPENSE Accounts (C_GlacctTc = COSEXP)")
        self.stdout.write("  3. Fetch BANK/CASH Accounts (C_GlacctTc = CASH)")

        self.stdout.write(self.style.WARNING("\n🔧 CONNECTIVITY TESTS:"))
        self.stdout.write("  T1. Test FINGLACCT (G/L Account) - COMM_USER")
        self.stdout.write("  T2. Test FINGLACCT (G/L Account) - SAP_USER")
        self.stdout.write("  T3. Test Transactional OData (baseline)")

        self.stdout.write(self.style.WARNING("\n📄 METADATA:"))
        self.stdout.write("  M.  View FINGLACCT Metadata")

        self.stdout.write(self.style.WARNING("\n🔍 OTHER:"))
        self.stdout.write("  L.  List available data sources")
        self.stdout.write("  A.  Run ALL connectivity tests")
        self.stdout.write("  G.  Get JWT Auth Token (for API testing)")

        self.stdout.write(self.style.WARNING("\n❌ EXIT:"))
        self.stdout.write("  Q.  Quit")
        self.stdout.write("\n" + "-"*80)

    def handle(self, *args, **options):
        while True:
            self.show_menu()
            choice = input("\nEnter choice: ").strip().upper()

            if choice == 'Q':
                self.stdout.write(self.style.SUCCESS("\n✓ Exiting...\n"))
                break

            # Fetch G/L Accounts
            elif choice == '1':
                self.fetch_gl_accounts(account_type=None, use_comm_user=True)
            elif choice == '2':
                self.fetch_gl_accounts(account_type='COSEXP', use_comm_user=True)
            elif choice == '3':
                self.fetch_gl_accounts(account_type='CASH', use_comm_user=True)

            # Connectivity Tests
            elif choice == 'T1':
                self.test_finglacct(use_comm_user=True)
            elif choice == 'T2':
                self.test_finglacct(use_comm_user=False)
            elif choice == 'T3':
                self.test_transactional_odata()

            # Metadata
            elif choice == 'M':
                self.test_metadata('Finglacct', use_comm_user=True)

            # Other
            elif choice == 'L':
                self.list_available_datasources(use_comm_user=True)
            elif choice == 'A':
                self.run_all_tests()
            elif choice == 'G':
                self.get_auth_token()

            else:
                self.stdout.write(self.style.ERROR(f"✗ Invalid choice: {choice}"))

            input("\n⏎ Press Enter to continue...")
