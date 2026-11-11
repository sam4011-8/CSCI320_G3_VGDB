"""New-release menu behavior; release_checks.mjs verifies SQL dates and scoring."""
from contextlib import redirect_stdout
from datetime import date, datetime
from io import StringIO
import unittest
from unittest.mock import Mock, patch

from src.vgdb.cli import Console
from src.vgdb.service import AppError, Service


class NewReleaseTests(unittest.TestCase):
    def test_displays_release_dates_player_counts_and_capped_playtime(self):
        service = Mock()
        service.new_releases.return_value = [
            {'game_id': 12, 'game_name': 'Neon Circuit', 'release_date': date(2026, 11, 3),
             'player_count': 3, 'capped_play_seconds': 153000},
            {'game_id': 11, 'game_name': 'Aurora Quest', 'release_date': date(2026, 11, 10),
             'player_count': 0, 'capped_play_seconds': 0},
        ]
        output = StringIO()
        with redirect_stdout(output):
            Console(service).new_releases(7)
        service.new_releases.assert_called_once_with()
        for expected in ('Top 5 new releases - current calendar month (UTC)',
                         "this month's distinct players", '20 hours per player per game',
                         '1. Neon Circuit (ID 12) | Released: 2026-11-03 | Players: 3 | Capped playtime: 42:30',
                         '2. Aurora Quest (ID 11) | Released: 2026-11-10 | Players: 0 | Capped playtime: 0:00'):
            self.assertIn(expected, output.getvalue())

    def test_explains_month_without_releases(self):
        service = Mock()
        service.new_releases.return_value = []
        output = StringIO()
        with redirect_stdout(output):
            Console(service).new_releases(7)
        self.assertIn('No games have been released this calendar month yet.', output.getvalue())

    def test_menu_opens_releases_and_returns_to_main_menu(self):
        service = Mock()
        service.new_releases.return_value = []
        console = Console(service)
        output = StringIO()
        with patch.object(console, 'login_menu', return_value={'uid': 7, 'username': 'dag'}), \
                patch('builtins.input', side_effect=['n', 'q']), redirect_stdout(output):
            console.run()
        service.new_releases.assert_called_once_with()
        self.assertIn('Top 5 new releases', output.getvalue())

    def test_rejects_ambiguous_report_timestamps_before_querying(self):
        database = Mock()
        for as_of in (datetime(2026, 11, 15), date(2026, 11, 15), '2026-11-15'):
            with self.subTest(as_of=as_of), self.assertRaisesRegex(AppError, 'timezone-aware'):
                Service(database).new_releases(as_of)
        database.rows.assert_not_called()


if __name__ == '__main__':
    unittest.main()
