"""Export actual recommendation SQL for the optional isolated PostgreSQL tests."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.vgdb.service import Service


class Capture:
    def rows(self, query, params):
        self.query, self.params = query, params
        return []


if __name__ == '__main__':
    capture = Capture()
    Service(capture).recommendations(1)
    output = ROOT / 'tmp/pgtest/recommendation-query.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'query': capture.query, 'params': capture.params}), encoding='utf-8')
    print('Prepared the actual recommendation SQL for isolated PostgreSQL checks.')
