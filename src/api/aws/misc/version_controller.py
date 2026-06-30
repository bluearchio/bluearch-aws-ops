#Do not change this, it is used to identify the version of the API.
CURRENT_VERSION='LOCAL'
import requests
import os
import sys
from rich import console
console = console.Console()

import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Environment variables
DEV = os.environ.get('BLUEARCH_DEBUG')

# API URL
if DEV:
    BASE_URL = f"https://releases.dev.bluearch.io/dev"
else:
    BASE_URL = "https://releases.bluearch.io/prod"

ENDPOINT = f"{BASE_URL}/get-updates"


def get_updates():
    headers = {
        'Content-Type': 'application/json'
    }
    
    payload = {
        'version': CURRENT_VERSION
    }
    
    try:
        response = requests.post(ENDPOINT, headers=headers, json=payload)
        if response is None:
            raise requests.exceptions.RequestException("No response received from the server")
        response.raise_for_status()
        data = response.json()
        return data['updates']
    except requests.exceptions.RequestException as req_ex:
        if hasattr(req_ex, 'response') and req_ex.response is not None:
            error_message = f"{req_ex.response.status_code} {req_ex.response.text}"
        else:
            error_message = f"{str(req_ex)}"
        raise Exception(error_message)
    except Exception as e:
        raise Exception(f"An error occurred: {str(e)}")