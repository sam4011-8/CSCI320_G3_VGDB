"""Recommendation menu, explanations, and service input validation."""
from contextlib import redirect_stdout
from io import StringIO
import unittest
from unittest.mock import Mock, patch

from src.vgdb.cli import Console
from src.vgdb.service import AppError, Service


def result(**updates):
    row = {
        'game_id': 12, 'game_name': 'Neon Circuit', 'platforms': 'PC',
        'platform_filtered': True, 'source': 'hybrid',
        'preference_score': 1, 'similar_player_score': 1, 'score': 1,
        'similar_player_count': 3, 'followed_player_count': 1,
        'recent_player_count': 4, 'capped_recent_seconds': 153000,
        'matched_genres': 'Racing', 'matched_contributors': 'Studio A',
    }
    row.update(updates)
    return row


class RecommendationTests(unittest.TestCase):
    def render(self, rows):
        service = Mock()
        service.recommendations.return_value = rows
        output = StringIO()
        with redirect_stdout(output):
            Console(service).recommendations(7)
        service.recommendations.assert_called_once_with(7)
        return output.getvalue()

    def test_personalized_recommendations_explain_both_signals_and_platforms(self):
        text = self.render([result()])
        for expected in ('up to 10 you have not played', 'Showing games released on platforms you own.',
                         'Neon Circuit (ID 12) | Personalized recommendation', 'Available on: PC',
                         'Matches genres: Racing', 'Matches contributors: Studio A',
                         'Played by 3 similar players', 'including 1 you follow'):
            self.assertIn(expected, text)

    def test_popular_fallback_is_labeled_for_owned_platforms(self):
        text = self.render([result(source='popular')])
        self.assertIn('Popular pick for your platforms', text)
        self.assertIn('4 players in the last 90 days', text)
        self.assertIn('capped playtime 42:30', text)
        self.assertNotIn('Personalized recommendation', text)
        self.assertNotIn('Played by', text)

    def test_global_fallback_explains_missing_platform_information(self):
        text = self.render([result(source='popular', platform_filtered=False, platforms='PC, Switch')])
        self.assertIn('No owned platforms set; considering all released platforms.', text)
        self.assertIn('| Popular pick', text)
        self.assertNotIn('Popular pick for your platforms', text)

    def test_catalog_without_popularity_is_not_presented_as_a_popular_or_personal_match(self):
        text = self.render([result(source='catalog', recent_player_count=0)])
        self.assertIn('| Available game', text)
        self.assertIn('No personalized match or recent popularity data', text)
        self.assertNotIn('Popular pick', text)
        self.assertNotIn('Personalized recommendation', text)

    def test_empty_candidate_pool_has_a_clear_message(self):
        self.assertIn('No unplayed, released games match your current settings.', self.render([]))

    def test_menu_uses_authenticated_user_and_returns_to_main_menu(self):
        service = Mock()
        service.recommendations.return_value = []
        console = Console(service)
        with patch.object(console, 'login_menu', return_value={'uid': 7, 'username': 'dag'}), \
                patch('builtins.input', side_effect=['d', 'q']), redirect_stdout(StringIO()):
            console.run()
        service.recommendations.assert_called_once_with(7)

    def test_invalid_viewer_cannot_get_generic_recommendations(self):
        database = Mock()
        for uid in (None, 0, -1, True, '7'):
            with self.subTest(uid=uid), self.assertRaisesRegex(AppError, 'signed-in user'):
                Service(database).recommendations(uid)
        database.rows.assert_not_called()


if __name__ == '__main__':
    unittest.main()
