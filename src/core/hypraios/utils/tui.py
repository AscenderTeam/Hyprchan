import sys
import time


ASCII_ART = """
[magenta]
      __  __                      ________                 
     / / / /_  ______  _____     / ____/ /_  ____ _____    
    / /_/ / / / / __ \/ ___/    / /   / __ \/ __ `/ __ \   
   / __  / /_/ / /_/ / /       / /___/ / / / /_/ / / / /   
  /_/ /_/\__, / .___/_/        \____/_/ /_/\__,_/_/ /_/    
        /____/_/                                           
[/magenta]
"""

def boot_log(text, delay=0.05, type="info"):
    prefix = {
        "info": "[  OK  ]",
        "warn": "[ WARN ]",
        "crit": "[ FATAL]",
        "lore": "[ HYPR ]"
    }
    color = {
        "info": "\033[32m", # Green
        "warn": "\033[33m", # Yellow
        "crit": "\033[31m", # Red
        "lore": "\033[35m", # Magenta
        "reset": "\033[0m"
    }
    
    sys.stdout.write(f"{color[type]}{prefix[type]}{color['reset']} {text}\n")
    sys.stdout.flush()
    time.sleep(delay)