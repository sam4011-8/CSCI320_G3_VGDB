"""Export the actual scoped and global popularity queries for isolated SQL checks."""
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
    service = Service(capture)
    service.followed_popular_games(1)
    followed = {'query': capture.query, 'params': capture.params}
    service.popular_games()
    output = ROOT / 'tmp/pgtest/followed-query.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'followed': followed,
                                 'global': {'query': capture.query, 'params': capture.params}}), encoding='utf-8')
    print('Prepared actual followed-user and global popularity SQL for isolated checks.')
