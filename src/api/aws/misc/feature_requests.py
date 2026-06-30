import os
import requests


DEV = os.environ.get('BLUEARCH_DEBUG')

if DEV:
    BASE_URL = f"https://feature-requests.dev.bluearch.io/dev"
else:
    BASE_URL = "https://feature-requests.bluearch.io/prod"

ENDPOINT = f"{BASE_URL}/submit-feature-request"

def send_feature_request(api_key, message):
    endpoint = f"{BASE_URL}/submit-feature-request"
    headers = {
        'Content-Type': 'application/json'
    }
    payload = {
        'api_key': api_key,
        'message': message
    }

    try:
        response = requests.post(endpoint, headers=headers, json=payload)
        if response.status_code != 200:
            error_data = response.json()
            error_message = error_data.get('message', 'An unknown error occurred')
            return False, error_message
        
        return True, "Feature request submitted successfully"
    except requests.exceptions.RequestException as e:
        return False, f"Request failed: {str(e)}"
    except Exception as e:
        return False, f"An unexpected error occurred: {str(e)}"
