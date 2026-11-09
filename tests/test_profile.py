"""Profile service and menu behavior checks."""
from contextlib import redirect_stdout
from io import StringIO
import unittest
from unittest.mock import Mock, patch

from src.vgdb.cli import Console
from src.vgdb.service import AppError, Service


class ProfileTests(unittest.TestCase):
    def test_missing_user_reports_error_without_querying_games(self):
        database = Mock()
        database.one.return_value = None
        with self.assertRaisesRegex(AppError, 'User profile not found'):
            Service(database).profile(999)
        database.rows.assert_not_called()

    def test_profile_displays_counts_personal_ratings_and_long_playtimes(self):
        service = Mock()
        service.profile.return_value = {
            'uid': 7, 'username': 'maya', 'collection_count': 3,
            'follower_count': 4, 'following_count': 2,
            'top_games': [
                {'game_id': 11, 'game_name': 'Aurora Quest', 'my_rating': 5, 'play_seconds': 90061},
                {'game_id': 12, 'game_name': 'Neon Circuit', 'my_rating': None, 'play_seconds': 1800},
            ],
        }
        output = StringIO()
        with redirect_stdout(output):
            Console(service).profile(7)
        service.profile.assert_called_once_with(7)
        text = output.getvalue()
        for expected in ('Profile: maya', 'Collections: 3', 'Followers: 4', 'Following: 2',
                         'highest rating, then total playtime',
                         '1. Aurora Quest (ID 11) | Your rating: 5/5 | Playtime: 25:01',
                         '2. Neon Circuit (ID 12) | Your rating: Not rated | Playtime: 0:30'):
            self.assertIn(expected, text)

    def test_profile_explains_empty_history(self):
        service = Mock()
        service.profile.return_value = {
            'uid': 8, 'username': 'new_user', 'collection_count': 0,
            'follower_count': 0, 'following_count': 0, 'top_games': [],
        }
        output = StringIO()
        with redirect_stdout(output):
            Console(service).profile(8)
        self.assertIn('Collections: 0', output.getvalue())
        self.assertIn('Followers: 0', output.getvalue())
        self.assertIn('Following: 0', output.getvalue())
        self.assertIn('No games played or rated yet', output.getvalue())

    def test_menu_opens_authenticated_users_profile_and_returns_to_menu(self):
        service = Mock()
        service.profile.return_value = {
            'uid': 7, 'username': 'maya', 'collection_count': 0,
            'follower_count': 0, 'following_count': 0, 'top_games': [],
        }
        console = Console(service)
        output = StringIO()
        with patch.object(console, 'login_menu', return_value={'uid': 7, 'username': 'maya'}), \
                patch('builtins.input', side_effect=['v', 'q']), redirect_stdout(output):
            console.run()
        service.profile.assert_called_once_with(7)
        self.assertIn('Profile: maya', output.getvalue())


if __name__ == '__main__':
    unittest.main()
