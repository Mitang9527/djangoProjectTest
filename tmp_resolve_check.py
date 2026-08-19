import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'djangoProjectTest.settings.test')
django.setup()
import loguru; loguru.logger.remove()
from django.urls import resolve, Resolver404

paths = [
    "/api/users/test/",
    "/api/users/api/test/",
    "/api/v1/users/test/",
    "/api/v1/users/api/test/",
]
for p in paths:
    try:
        m = resolve(p)
        view = m.func
        name = getattr(view, '__name__', str(view))
        if hasattr(view, '__self__'):
            name = f"{view.__self__.__class__.__name__}.{name}"
        print(f"MATCH  {p}  ->  {m.view_name}  ({name})")
    except Resolver404:
        print(f"404    {p}")
