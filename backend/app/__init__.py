import os

# Номер релиза вручную, плюс короткий хеш коммита, из которого собран образ (его подставляет deploy/update.sh), —
# так по «Версия …» в настройках видно, какой именно код работает.
BASE_VERSION = "0.14.0"
BUILD = os.environ.get("HOMECAL_BUILD", "").strip()[:12]
__version__ = f"{BASE_VERSION}+{BUILD}" if BUILD else BASE_VERSION
