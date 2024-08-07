import os
from pathlib import Path
from dotenv import load_dotenv
from django.apps import AppConfig

dotenv_path = os.path.join(Path(__file__).resolve().parent.parent, '.env')
load_dotenv(dotenv_path)

def create_default_store(sender, **kwargs):
	'''
		Creates a default store record.
	'''
	from egrn_service.models import Store
	from .services import get_store_from_middleware
	
	if not Store.objects.exists():
		default_store_data = get_store_from_middleware(byd_cost_center_code=os.getenv('HQ_STORE_COST_CENTER_CODE'))
		Store().create_store(default_store_data[0])


class EgrnServiceConfig(AppConfig):
	default_auto_field = 'django.db.models.BigAutoField'
	name = 'egrn_service'
	
	def ready(self):
		create_default_store(sender=self)