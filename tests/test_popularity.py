"""Popularity menu behavior; popularity_checks.mjs verifies the actual SQL results."""
from contextlib import redirect_stdout
from io import StringIO
import unittest
from unittest.mock import Mock, patch

from src.vgdb.cli import Console


class PopularityTests(unittest.TestCase):
    def test_displays_rank_player_count_capped_time_and_scoring_rule(self):
        service = Mock()
        service.popular_games.return_value = [
            {'game_id': 12, 'game_name': 'Neon Circuit', 'player_count': 3,
             'capped_play_seconds': 153000},
            {'game_id': 11, 'game_name': 'Aurora Quest', 'player_count': 2,
             'capped_play_seconds': 72000},
        ]
        output = StringIO()
        with redirect_stdout(output):
            Console(service).popularity(7)
        service.popular_games.assert_called_once_with()
        text = output.getvalue()
        for expected in ('Top 20 popular games - last 90 days',
                         'Ranked by distinct players', '20 hours per player per game',
                         '1. Neon Circuit (ID 12) | Players: 3 | Capped playtime: 42:30',
                         '2. Aurora Quest (ID 11) | Players: 2 | Capped playtime: 20:00'):
            self.assertIn(expected, text)

    def test_explains_empty_recent_activity(self):
        service = Mock()
        service.popular_games.return_value = []
        output = StringIO()
        with redirect_stdout(output):
            Console(service).popularity(7)
        self.assertIn('No completed plays in the last 90 days.', output.getvalue())

    def test_menu_opens_popularity_and_returns_without_more_prompts(self):
        service = Mock()
        service.popular_games.return_value = []
        console = Console(service)
        output = StringIO()
        with patch.object(console, 'login_menu', return_value={'uid': 7, 'username': 'dag'}), \
                patch('builtins.input', side_effect=['t', 'q']), redirect_stdout(output):
            console.run()
        service.popular_games.assert_called_once_with()
        self.assertIn('Top 20 popular games', output.getvalue())


if __name__ == '__main__':
    unittest.main()
