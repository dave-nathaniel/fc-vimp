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
	from .services import Middleware
	
	if not Store.objects.exists():
		middleware = Middleware()
		default_store_data = middleware.get_store(byd_cost_center_code=os.getenv('HQ_STORE_COST_CENTER_CODE'))
		Store().create_store(default_store_data[0])


class EgrnServiceConfig(AppConfig):
	default_auto_field = 'django.db.models.BigAutoField'
	name = 'egrn_service'
	verbose_name = '2. Goods Receipt Note'
	
	def ready(self):
		create_default_store(sender=self)