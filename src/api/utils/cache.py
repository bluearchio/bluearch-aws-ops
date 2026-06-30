import os, shutil
import json
import base64
import hashlib
import threading
from datetime import timedelta
from functools import wraps
from typing import Any, Callable, Optional, Dict, List
from utils.logger_config import log
from fernet import Fernet, InvalidToken
from cachetools import LRUCache
import pwd
import grp

class ReadWriteLock:
    """
    A simple Read-Write lock.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._readers_count = 0

    def acquire_read(self):
        with self._lock:
            self._readers_count += 1
            if self._readers_count == 1:
                self._write_lock = threading.Lock()
                self._write_lock.acquire()

    def release_read(self):
        with self._lock:
            self._readers_count -= 1
            if self._readers_count == 0:
                self._write_lock.release()

    def acquire_write(self):
        self._lock.acquire()
        self._write_lock.acquire()

    def release_write(self):
        self._write_lock.release()
        self._lock.release()

    def __enter__(self):
        self.acquire_read()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release_read()

class SecureCache:
    """
    A secure caching mechanism that handles in-memory and disk-based caching
    with encryption and expiration.
    """
    _instances = {}
    _lock = threading.Lock()

    def __new__(cls, cache_filename: str, expiry_minutes: int = 600):
        with cls._lock:
            if cache_filename not in cls._instances:
                instance = super(SecureCache, cls).__new__(cls)
                cls._instances[cache_filename] = instance
            return cls._instances[cache_filename]

    def __init__(self, cache_filename: str, expiry_minutes: int = 600):
        if hasattr(self, 'initialized'):
            return
        
        self.expiry = timedelta(minutes=expiry_minutes)
        self.memory_cache = {}
        self.lock = ReadWriteLock()
        self.in_memory_cache = LRUCache(maxsize=1000)
        
        # Get the actual user (even when running with sudo)
        sudo_user = os.environ.get('SUDO_USER')
        current_user = sudo_user if sudo_user else os.environ.get('USER')
        key_material = f"{current_user or 'local'}:{cache_filename}".encode("utf-8")
        self.fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(key_material).digest()))
        
        config_dir = os.path.expanduser(f"~{current_user}/.bluearch")
        
        # Create directory if it doesn't exist
        os.makedirs(config_dir, mode=0o755, exist_ok=True)
        
        self.cache_file = os.path.join(config_dir, cache_filename)
        
        # Create empty cache file if it doesn't exist
        if not os.path.exists(self.cache_file):
            with open(self.cache_file, 'wb') as f:
                encrypted_content = self.fernet.encrypt(json.dumps({}).encode())
                f.write(encrypted_content)
            os.chmod(self.cache_file, 0o600)
        
        # Fix permissions for existing directory and files
        self._fix_permissions(config_dir, current_user)
        self._fix_permissions(self.cache_file, current_user)
        
        self.initialized = True
        self._load_cache()

    def _load_cache(self):
        try:
            with open(self.cache_file, 'rb') as f:
                encrypted_content = f.read()
            decrypted_content = self.fernet.decrypt(encrypted_content)
            self.memory_cache = json.loads(decrypted_content.decode())
        except (FileNotFoundError, json.JSONDecodeError, InvalidToken):
            self.memory_cache = {}

    def _save_cache(self):
        try:
            # Get the actual user (even when running with sudo)
            sudo_user = os.environ.get('SUDO_USER')
            current_user = sudo_user if sudo_user else os.environ.get('USER')
            
            # Ensure config directory exists
            config_dir = os.path.expanduser(f"~{current_user}/.bluearch")
            os.makedirs(config_dir, mode=0o755, exist_ok=True)
            
            # Fix directory permissions
            self._fix_permissions(config_dir, current_user)
            
            # Write to cache file
            encrypted_content = self.fernet.encrypt(json.dumps(self.memory_cache).encode())
            with open(self.cache_file, 'wb') as f:
                f.write(encrypted_content)
            
            # Fix file permissions
            os.chmod(self.cache_file, 0o600)
            
            # Set proper ownership if running as root
            if os.geteuid() == 0 and sudo_user:
                uid = pwd.getpwnam(sudo_user).pw_uid
                gid = grp.getgrnam(sudo_user).gr_gid
                os.chown(self.cache_file, uid, gid)
                
        except Exception as e:
            log.error(f"Failed to save cache: {str(e)}")
            # Create an empty cache file if it doesn't exist
            if not os.path.exists(self.cache_file):
                with open(self.cache_file, 'wb') as f:
                    encrypted_content = self.fernet.encrypt(json.dumps({}).encode())
                    f.write(encrypted_content)
                os.chmod(self.cache_file, 0o600)

    def get(self, key: str) -> Optional[Any]:
        with self.lock:
            if key in self.in_memory_cache:
                log.debug(f"Memory Cache Hit: {key}")
                return self.in_memory_cache[key]
            if key in self.memory_cache:
                log.debug(f"Disk Cache Hit: {key}")
                value = self.memory_cache[key]
                self.in_memory_cache[key] = value
                return value
        log.debug(f"Cache Miss: {key}")
        return None

    def set(self, key: str, value: Any) -> None:
        with self.lock:
            self.in_memory_cache[key] = value
            self.memory_cache[key] = value
            self._save_cache()

    def get_multiple_keys(self, keys: List[str]) -> Dict[str, Any]:
        with self.lock:
            return {key: self.get(key) for key in keys if self.get(key) is not None}

    def invalidate_cache(self) -> None:
        with self.lock:
            self.in_memory_cache.clear()
            self.memory_cache.clear()
            if os.path.exists(self.cache_file):
                os.remove(self.cache_file)
            log.debug("Cache Invalidated.")

    def _fix_permissions(self, path: str, owner: str):
        """Fix permissions and ownership of a file or directory."""
        try:
            # Set file permissions
            if os.path.isfile(path):
                os.chmod(path, 0o600)  # rw------- for files
            else:
                os.chmod(path, 0o755)  # rwxr-xr-x for directories

            # Set ownership if running as root
            if os.geteuid() == 0 and owner:
                uid = pwd.getpwnam(owner).pw_uid
                gid = grp.getgrnam(owner).gr_gid
                os.chown(path, uid, gid)
        except Exception as e:
            log.debug(f"Failed to fix permissions for {path}: {str(e)}")

def delete_cache():
    try:
        cache_path = os.path.expanduser('~/.bluearch')
        if os.path.exists(cache_path):
            if os.path.isdir(cache_path):
                shutil.rmtree(cache_path)
            else:
                os.remove(cache_path)
            log.debug("Disk Cache Invalidated.")
        else:
            log.debug("Cache path does not exist.")
    except Exception as e:
        log.debug(f"Failed to invalidate cache: {str(e)}")


def cache_result(cache: SecureCache, key_func: Callable[..., str]) -> Callable:
    """
    Decorator to cache function results using SecureCache.
    The key_func generates a unique key based on function arguments.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = key_func(*args, **kwargs)
            cached_result = cache.get(key)
            if cached_result is not None:
                log.debug(f"Returning cached result for key: {key}")
                return cached_result

            log.debug(f"Executing function {func.__name__} for key: {key}")
            result = func(*args, **kwargs)
            cache.set(key, result)
            return result
        return wrapper
    return decorator

def fix_cache_permissions():
    """Utility function to fix permissions of existing cache files."""
    try:
        sudo_user = os.environ.get('SUDO_USER')
        current_user = sudo_user if sudo_user else os.environ.get('USER')
        
        config_dir = os.path.expanduser(f"~{current_user}/.bluearch")
        if not os.path.exists(config_dir):
            return
            
        # Fix directory permissions
        os.chmod(config_dir, 0o755)
        
        # Fix ownership if running as root
        if os.geteuid() == 0 and current_user:
            uid = pwd.getpwnam(current_user).pw_uid
            gid = grp.getgrnam(current_user).gr_gid
            os.chown(config_dir, uid, gid)
            
            # Fix all files in the directory
            for filename in os.listdir(config_dir):
                filepath = os.path.join(config_dir, filename)
                if os.path.isfile(filepath):
                    os.chmod(filepath, 0o600)
                    os.chown(filepath, uid, gid)
    except Exception as e:
        log.debug(f"Failed to fix cache permissions: {str(e)}")
