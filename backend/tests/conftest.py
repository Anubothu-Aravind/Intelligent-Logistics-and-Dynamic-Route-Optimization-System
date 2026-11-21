import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# tests always run against an isolated temporary database and a small scenario
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["ORDER_COUNT"] = "30"
os.environ["VEHICLE_COUNT"] = "5"
os.environ["CITY_SOURCE"] = "synthetic"   # deterministic + offline
