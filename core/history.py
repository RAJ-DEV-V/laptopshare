"""
LaptopShare Transfer History
Persists transfer history records to JSON in AppData.
"""

import time
import json
from pathlib import Path
from typing import List, Dict, Any
from dataclasses import dataclass, asdict

from .config import get_app_data_dir

@dataclass
class TransferRecord:
    id: str
    direction: str  # "sent" or "received"
    peer_name: str
    peer_ip: str
    files_count: int
    total_bytes: int
    status: str     # "Completed", "Failed", "Cancelled", "Interrupted"
    duration_sec: float
    timestamp: float
    destination_dir: str = ""
    error_message: str = ""

class HistoryManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(HistoryManager, cls).__new__(cls)
            cls._instance._load()
        return cls._instance

    def _get_history_file(self) -> Path:
        return get_app_data_dir() / "history.json"

    def _load(self):
        self.records: List[TransferRecord] = []
        path = self._get_history_file()
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    data = json.loads(content)
                    for item in data:
                        self.records.append(TransferRecord(**item))
            except Exception as e:
                self.records = []

    def save(self):
        path = self._get_history_file()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump([asdict(r) for r in self.records], f, indent=2)
        except Exception as e:
            print(f"[History] Error saving history: {e}")

    def add_record(self, record: TransferRecord):
        # Insert newest first
        self.records.insert(0, record)
        # Keep maximum 200 records
        if len(self.records) > 200:
            self.records = self.records[:200]
        self.save()

    def get_all(self) -> List[TransferRecord]:
        return list(self.records)

    def clear(self):
        self.records.clear()
        self.save()
