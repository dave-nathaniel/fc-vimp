import os
import sys
from django.core.wsgi import get_wsgi_application
from pathlib import Path
from dotenv import load_dotenv

dotenv_path = os.path.join(Path(__file__).resolve().parent.parent, '.env')
load_dotenv(dotenv_path)

# Add project directory to the sys.path
path_home = str(Path(__file__).parents[1])
if path_home not in sys.path:
	sys.path.append(path_home)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'vimp.settings')

application = get_wsgi_application()
