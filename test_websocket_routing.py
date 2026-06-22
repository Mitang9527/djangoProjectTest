import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / 'apps'))

os.environ['DJANGO_SETTINGS_MODULE'] = 'djangoProjectTest.settings.dev'

import django
django.setup()

from djangoProjectTest.routing import websocket_urlpatterns
print('Import success! Number of routes:', len(websocket_urlpatterns))
for route in websocket_urlpatterns:
    print('  -', route.pattern._route)

print()
print('Testing asgi import...')
import djangoProjectTest.asgi
print('ASGI application:', hasattr(djangoProjectTest.asgi, 'application'))