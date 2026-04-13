import os
from hyprchan.settings import EXTENSIONS_ENABLED
from hyprchan.config.personalization import load_personalization_config

print(f"EXTENSIONS_ENABLED: {EXTENSIONS_ENABLED}")
config = load_personalization_config()
print(f"Config extensions enabled: {config.extensions.enabled}")
print(f"Env HYPRCHAN_EXTENSIONS_ENABLED: {os.getenv('HYPRCHAN_EXTENSIONS_ENABLED')}")
