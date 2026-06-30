from utils.cache import SecureCache

# Singleton instances of caches
CLOUDFORMATION_CACHE = SecureCache(cache_filename='bluearch_cfn_cache.json', expiry_minutes=600)
AUTH_CACHE = SecureCache(cache_filename='bluearch_auth_cache.json', expiry_minutes=600)
ASSUMED_ROLE_CACHE = SecureCache(cache_filename='bluearch_assumed_role_cache.json', expiry_minutes=600)