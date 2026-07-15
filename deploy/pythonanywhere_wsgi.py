# PythonAnywhere WSGI configuration for the traffic_arteries backend.
#
# This is a REFERENCE copy. On PythonAnywhere, paste these contents into the
# Web tab's WSGI file (the real path is
# /var/www/yonatanperi_pythonanywhere_com_wsgi.py). The project's own
# backend/traffic_arteries/wsgi.py is used for local development and is left
# unchanged.
#
# Env vars set in a bash console do NOT reach the web worker, so production
# secrets/config are exported here — remember to replace DJANGO_SECRET_KEY
# with a real random value.

import os
import sys

path = "/home/yonatanperi/traffic-arteries/backend"
if path not in sys.path:
    sys.path.insert(0, path)

os.environ["DJANGO_SETTINGS_MODULE"] = "traffic_arteries.settings"
os.environ["DJANGO_DEBUG"] = "False"
os.environ["DJANGO_SECRET_KEY"] = "REPLACE-WITH-A-REAL-RANDOM-SECRET"
os.environ["DJANGO_ALLOWED_HOSTS"] = "yonatanperi.pythonanywhere.com"
os.environ["CORS_ALLOWED_ORIGINS"] = "https://traffic-arteries.pages.dev"

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
