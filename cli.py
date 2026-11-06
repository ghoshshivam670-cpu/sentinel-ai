import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from sentinel.cli import app

if __name__ == "__main__":
    app()
