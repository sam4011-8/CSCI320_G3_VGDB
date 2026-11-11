"""Export the application's new-release SQL for isolated PostgreSQL checks."""
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
    Service(capture).new_releases()
    output = ROOT / 'tmp/pgtest/release-query.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'query': capture.query, 'params': capture.params}), encoding='utf-8')
    print('Prepared the actual new-release SQL for isolated PostgreSQL checks.')
