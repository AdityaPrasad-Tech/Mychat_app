import os

os.environ.setdefault("DJANGO_DEBUG", "1")

from .settings import *  # noqa: F403,F401,E402
