import pytest
import sys
from coverage import Coverage
import os

if __name__ == "__main__":
    # Set environment variable for UTF-8 encoding
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    
    # Initialize coverage with explicit settings
    cov = Coverage(
        source=['cli'],
        omit=[
            'tests/*',
            '*/__init__.py',
            '*/__pycache__/*'
        ],
        branch=True,
    )
    cov.start()
    
    # Run pytest with specific arguments
    exit_code = pytest.main([
        'tests',  # Directory containing tests
        '-v',    # Verbose output
        '--capture=no',
        '--strict-markers',  # Ensure all markers are registered
        '--failed-first',    # Run failed tests first
        '-x',               # Exit on first failure
        '--maxfail=1',      # Stop after first failure
        '--asyncio-mode=strict'  # Add strict asyncio mode
    ])
    
    cov.stop()
    cov.save()
    
    print("\nGenerating coverage reports...")
    cov.report(show_missing=True)
    
    # Ensure non-zero exit code propagates
    if exit_code != 0:
        print(f"\nTests failed with exit code: {exit_code}")
        sys.exit(1)
    
    sys.exit(exit_code)
