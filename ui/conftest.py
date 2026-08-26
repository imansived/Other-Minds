import sys
from pathlib import Path

# The Streamlit script does `import api`, which resolves relative to ui/.
sys.path.insert(0, str(Path(__file__).resolve().parent))
