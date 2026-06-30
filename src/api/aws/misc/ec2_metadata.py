import requests
from utils.logger_config import log
from functools import lru_cache

@lru_cache(maxsize=None)
def get_ec2_public_dns():
    """Get the public DNS of the EC2 instance. Return localhost if not running on EC2."""
    token_url = "http://169.254.169.254/latest/api/token"
    metadata_url = "http://169.254.169.254/latest/meta-data/public-hostname"
    headers = {"X-aws-ec2-metadata-token-ttl-seconds": "21600"}

    try:
        token_response = requests.put(token_url, headers=headers, timeout=1)
        token = token_response.text.strip()

        metadata_headers = {"X-aws-ec2-metadata-token": token}
        metadata_response = requests.get(metadata_url, headers=metadata_headers, timeout=1)
        return metadata_response.text.strip()
    except requests.exceptions.RequestException as e:
        return "http://localhost:8000"