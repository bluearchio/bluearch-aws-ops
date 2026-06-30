import logging
import os

class Logger:
    def __init__(self, name: str, log_file: str = 'bluearch_cli.log'):
        self.log = logging.getLogger(name)
        self.log.setLevel(logging.DEBUG)  # Set to lowest level to catch all messages

        # File handler setup
        if os.getenv('BLUEARCH_DEBUG') == '1':
            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(logging.DEBUG)
            file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(file_formatter)
            self.log.addHandler(file_handler)

        # Console handler setup
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG if os.getenv('BLUEARCH_DEBUG') == '1' else logging.INFO)
        console_formatter = logging.Formatter('%(levelname)s - %(message)s') if os.getenv('BLUEARCH_DEBUG') == '1' else logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(console_formatter)
        self.log.addHandler(console_handler)

    def info(self, *args, **kwargs):
        self.log.info(*args, **kwargs)

    def error(self, *args, **kwargs):
        self.log.error(*args, **kwargs)

    def debug(self, *args, **kwargs):
        self.log.debug(*args, **kwargs)

    def warning(self, *args, **kwargs):
        self.log.warning(*args, **kwargs)

    def warn(self, *args, **kwargs):  # alias for backwards-compat
        self.log.warning(*args, **kwargs)

    def critical(self, *args, **kwargs):
        self.log.critical(*args, **kwargs)

    def exception(self, *args, **kwargs):
        self.log.exception(*args, **kwargs)

log = Logger('alerts_v2')