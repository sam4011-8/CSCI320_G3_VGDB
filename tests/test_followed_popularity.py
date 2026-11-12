"""Followed-user popularity menu behavior; SQL results are tested separately."""
from contextlib import redirect_stdout
from io import StringIO
import unittest
from unittest.mock import Mock, patch

from src.vgdb.cli import Console
from src.vgdb.service import AppError, Service


class FollowedPopularityTests(unittest.TestCase):
    def test_displays_followed_player_counts_and_capped_time(self):
        service = Mock()
        service.followed_popular_games.return_value = [
            {'game_id': 12, 'game_name': 'Neon Circuit', 'player_count': 3,
             'capped_play_seconds': 153000},
            {'game_id': 11, 'game_name': 'Aurora Quest', 'player_count': 1,
             'capped_play_seconds': 3600},
        ]
        output = StringIO()
        with redirect_stdout(output):
            Console(service).followed_popularity(7)
        service.followed_popular_games.assert_called_once_with(7)
        for expected in ('Top 20 popular games among people you follow - last 90 days',
                         'distinct followed players', '20 hours per player per game',
                         '1. Neon Circuit (ID 12) | Players you follow: 3 | Capped playtime: 42:30',
                         '2. Aurora Quest (ID 11) | Players you follow: 1 | Capped playtime: 1:00'):
            self.assertIn(expected, output.getvalue())

    def test_explains_empty_followed_activity(self):
        service = Mock()
        service.followed_popular_games.return_value = []
        output = StringIO()
        with redirect_stdout(output):
            Console(service).followed_popularity(7)
        self.assertIn('No completed plays from people you follow in the last 90 days.', output.getvalue())

    def test_menu_uses_authenticated_user_without_prompting_for_another_id(self):
        service = Mock()
        service.followed_popular_games.return_value = []
        console = Console(service)
        output = StringIO()
        with patch.object(console, 'login_menu', return_value={'uid': 7, 'username': 'dag'}), \
                patch('builtins.input', side_effect=['f', 'q']), redirect_stdout(output):
            console.run()
        service.followed_popular_games.assert_called_once_with(7)
        service.popular_games.assert_not_called()
        self.assertIn('Top 20 popular games among people you follow', output.getvalue())

    def test_invalid_viewer_never_falls_back_to_global_popularity(self):
        database = Mock()
        for uid in (None, 0, -1, True, '7'):
            with self.subTest(uid=uid), self.assertRaisesRegex(AppError, 'signed-in user'):
                Service(database).followed_popular_games(uid)
        database.rows.assert_not_called()


if __name__ == '__main__':
    unittest.main()
