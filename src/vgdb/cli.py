"""Interactive video game database CLI. Schema installation is a separate action."""
import argparse
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from getpass import getpass
from pathlib import Path

import psycopg

from .db import Settings, SetupError, connect
from .service import (AppError, SearchFilters, Service, hours_minutes,
                      POPULARITY_DAYS, POPULARITY_CAP_HOURS)


def number(prompt):
    try:
        value = int(input(prompt).strip())
    except ValueError as error:
        raise AppError('Enter an integer ID or value.') from error
    if value <= 0:
        raise AppError('Enter a positive value.')
    return value


def optional_number(prompt):
    value = input(prompt).strip()
    if not value:
        return None
    if not value.isdigit() or int(value) <= 0:
        raise AppError('Enter a positive ID, or leave the filter blank.')
    return int(value)


def optional_date(prompt):
    value = input(prompt).strip()
    try:
        return date.fromisoformat(value) if value else None
    except ValueError as error:
        raise AppError('Use a date in YYYY-MM-DD format.') from error


def optional_price(prompt):
    value = input(prompt).strip()
    try:
        return Decimal(value) if value else None
    except InvalidOperation as error:
        raise AppError('Enter a decimal price, or leave the filter blank.') from error


def timestamp(text):
    try:
        value = datetime.fromisoformat(text.strip().replace('Z', '+00:00'))
    except ValueError as error:
        raise AppError('Use an ISO timestamp, such as 2026-10-22T10:30:00Z.') from error
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def display(rows):
    if not rows:
        print('(No results)')
    for row in rows:
        print(' | '.join(f'{key}: {value if value is not None else "-"}' for key, value in row.items()))


def action_error(error):
    if isinstance(error, psycopg.errors.UniqueViolation):
        print('That username, email, membership, follow, or session already exists.')
    elif isinstance(error, psycopg.errors.ForeignKeyViolation):
        print('A referenced record does not exist or is still in use.')
    elif isinstance(error, psycopg.errors.CheckViolation):
        print('Cannot save:', error.diag.message_primary)
    elif isinstance(error, psycopg.Error):
        print('Database operation failed:', error.diag.message_primary or error.__class__.__name__)
    else:
        print(error)


class Console:
    def __init__(self, service):
        self.service = service

    def login_menu(self):
        while True:
            choice = input('\n[l]ogin, [n]ewuser, [q]uit: ').strip().lower()
            try:
                if choice == 'q':
                    return None
                if choice in ('n', 'newuser'):
                    username = input('New username: ')
                    first, last = input('First name: '), input('Last name: ')
                    email = input('Email: ')
                    password = getpass('New password (8+ characters): ')
                    if password != getpass('Confirm password: '):
                        raise AppError('Passwords do not match.')
                    user = self.service.register(username, password, first, last, email)
                    print(f'Account {user["username"]} created. Log in to continue.')
                elif choice == 'l':
                    user = self.service.login(input('Username: '), getpass('Password: '))
                    print(f'Welcome, {user["username"]}.')
                    return user
                else:
                    print('Choose l, n, or q.')
            except (ValueError, psycopg.Error) as error:
                action_error(error)

    def run(self):
        print('CSCI 320 Group 3 VGDB')
        while (user := self.login_menu()) is not None:
            while True:
                choice = input('\n[v]iew profile [d]iscover recommendations '
                               '[t]op 20 popular [f]ollowed top 20 [n]ew releases '
                               '[c]ollections [g]ames [p]lay [r]ate [s]ocial '
                               '[o]wned platforms [l]ogout [q]uit: ').strip().lower()
                if choice == 'q':
                    return
                if choice == 'l':
                    break
                actions = {'v': self.profile, 't': self.popularity, 'n': self.new_releases,
                           'f': self.followed_popularity,
                           'd': self.recommendations,
                           'c': self.collections, 'g': self.games, 'p': self.play,
                           'r': self.rate, 's': self.social, 'o': self.platforms}
                if choice not in actions:
                    print('Choose one of the listed letters.')
                    continue
                try:
                    actions[choice](user['uid'])
                except (ValueError, psycopg.Error) as error:
                    action_error(error)

    def profile(self, uid):
        profile = self.service.profile(uid)
        print(f'\nProfile: {profile["username"]}')
        print(f'Collections: {profile["collection_count"]}')
        print(f'Followers: {profile["follower_count"]}')
        print(f'Following: {profile["following_count"]}')
        print('\nYour top 10 games (highest rating, then total playtime; unrated games last):')
        if not profile['top_games']:
            print('No games played or rated yet. Record a play to start your list.')
        for rank, game in enumerate(profile['top_games'], 1):
            rating = f'{game["my_rating"]}/5' if game['my_rating'] is not None else 'Not rated'
            print(f'{rank}. {game["game_name"]} (ID {game["game_id"]}) | '
                  f'Your rating: {rating} | Playtime: {hours_minutes(game["play_seconds"])}')

    def popularity(self, uid):
        games = self.service.popular_games()
        print(f'\nTop 20 popular games - last {POPULARITY_DAYS} days')
        print(f'Ranked by distinct players, then playtime capped at {POPULARITY_CAP_HOURS} hours '
              'per player per game.')
        if not games:
            print(f'No completed plays in the last {POPULARITY_DAYS} days.')
        for rank, game in enumerate(games, 1):
            print(f'{rank}. {game["game_name"]} (ID {game["game_id"]}) | '
                  f'Players: {game["player_count"]} | '
                  f'Capped playtime: {hours_minutes(game["capped_play_seconds"])}')

    def followed_popularity(self, uid):
        games = self.service.followed_popular_games(uid)
        print(f'\nTop 20 popular games among people you follow - last {POPULARITY_DAYS} days')
        print(f'Ranked by distinct followed players, then playtime capped at {POPULARITY_CAP_HOURS} hours '
              'per player per game.')
        if not games:
            print(f'No completed plays from people you follow in the last {POPULARITY_DAYS} days.')
        for rank, game in enumerate(games, 1):
            print(f'{rank}. {game["game_name"]} (ID {game["game_id"]}) | '
                  f'Players you follow: {game["player_count"]} | '
                  f'Capped playtime: {hours_minutes(game["capped_play_seconds"])}')

    def new_releases(self, uid):
        games = self.service.new_releases()
        print('\nTop 5 new releases - current calendar month (UTC)')
        print("Ranked by this month's distinct players, then playtime capped at "
              f'{POPULARITY_CAP_HOURS} hours per player per game; latest releases break remaining ties.')
        if not games:
            print('No games have been released this calendar month yet.')
        for rank, game in enumerate(games, 1):
            print(f'{rank}. {game["game_name"]} (ID {game["game_id"]}) | '
                  f'Released: {game["release_date"]} | Players: {game["player_count"]} | '
                  f'Capped playtime: {hours_minutes(game["capped_play_seconds"])}')

    def recommendations(self, uid):
        games = self.service.recommendations(uid)
        print('\nRecommended games - up to 10 you have not played')
        if not games:
            print('No unplayed, released games match your current settings.')
            return
        if games[0]['platform_filtered']:
            print('Showing games released on platforms you own.')
        else:
            print('No owned platforms set; considering all released platforms.')
        for rank, game in enumerate(games, 1):
            if game['source'] in ('popular', 'catalog'):
                if game['source']=='popular':
                    label = 'Popular pick for your platforms' if game['platform_filtered'] else 'Popular pick'
                    reasons = [f'{game["recent_player_count"]} players in the last {POPULARITY_DAYS} days',
                               f'capped playtime {hours_minutes(game["capped_recent_seconds"])}']
                else:
                    label = 'Available game'
                    reasons = ['No personalized match or recent popularity data']
            else:
                label = 'Personalized recommendation'
                reasons = []
                if game['matched_genres']:
                    reasons.append('Matches genres: ' + game['matched_genres'])
                if game['matched_contributors']:
                    reasons.append('Matches contributors: ' + game['matched_contributors'])
                if game['similar_player_count']:
                    reasons.append(f'Played by {game["similar_player_count"]} similar players')
                if game['followed_player_count']:
                    reasons.append(f'including {game["followed_player_count"]} you follow')
            print(f'{rank}. {game["game_name"]} (ID {game["game_id"]}) | {label}')
            print('   Available on: ' + game['platforms'])
            print('   Why: ' + '; '.join(reasons))

    def collections(self, uid):
        while True:
            rows = self.service.collections(uid)
            for row in rows:
                row['hours_minutes'] = hours_minutes(row.pop('total_seconds'))
            display(rows)
            choice = input('[n]ew [a]dd game [r]emove game [e]dit name [d]elete collection [b]ack: ').strip().lower()
            if choice == 'b':
                return
            try:
                if choice == 'n':
                    print('Created:', self.service.create_collection(uid, input('Collection name: '))['collection_id'])
                elif choice == 'e':
                    self.service.rename_collection(uid, number('Collection ID: '), input('New name: '))
                    print('Renamed.')
                elif choice == 'd':
                    collection_id = number('Collection ID: ')
                    if input('Delete this collection and its memberships? Type yes: ').strip().lower() == 'yes':
                        self.service.delete_collection(uid, collection_id)
                        print('Deleted.')
                elif choice == 'a':
                    collection_id, game_id = number('Collection ID: '), number('Game ID: ')
                    display(self.service.platforms())
                    owned = self.service.add_game(uid, collection_id, game_id, number('Selected platform ID: '))
                    if not owned:
                        print('Warning: you do not own the selected platform. The game was added as allowed.')
                    else:
                        print('Game added.')
                elif choice == 'r':
                    self.service.remove_game(uid, number('Collection ID: '), number('Game ID: '))
                    print('Game removed; recorded play history is retained.')
                else:
                    print('Choose one of the listed letters.')
            except (ValueError, psycopg.Error) as error:
                action_error(error)

    def games(self, uid):
        print('Leave any filter blank to skip it. Multiple filters are combined.')
        title = input('Game name contains: ').strip()
        developer = input('Developer contains: ').strip()
        display(self.service.platforms())
        platform = optional_number('Platform ID: ')
        display(self.service.genres())
        genre = optional_number('Genre ID: ')
        filters = SearchFilters(title, developer, platform, genre,
                                optional_date('Released on/after YYYY-MM-DD: '),
                                optional_date('Released on/before YYYY-MM-DD: '),
                                optional_price('Minimum price USD: '), optional_price('Maximum price USD: '))
        filters.validate()
        sort, descending, offset = 'default', False, 0
        while True:
            rows = self.service.search(uid, filters, sort, descending, offset)
            print(f'\nResults {offset + 1}-{offset + len(rows)}' if rows else '\nNo results on this page.')
            for row in rows:
                row['playtime'] = hours_minutes(row.pop('play_seconds'))
                display([row])
            print('Price is the lowest available platform price; date is earliest release; genre sorting uses first genre.')
            command = input('[n]ext [p]revious [s]ort [b]ack: ').strip().lower()
            if command == 'b':
                return
            if command == 'n':
                if len(rows) == 50:
                    offset += 50
                else:
                    print('This is the last page.')
            elif command == 'p':
                offset = max(0, offset - 50)
            elif command == 's':
                new_sort = input('Sort: name, price, genre, year: ').strip().lower()
                direction = input('Direction: asc or desc: ').strip().lower()
                if new_sort not in ('name', 'price', 'genre', 'year') or direction not in ('asc', 'desc'):
                    print('Choose a listed sort and direction.')
                    continue
                sort, descending, offset = new_sort, direction == 'desc', 0
            else:
                print('Choose n, p, s, or b.')

    def play(self, uid):
        choice = input('[i]ndividual game or [r]andom from a collection: ').strip().lower()
        if choice == 'r':
            display(self.service.collections(uid))
            game = self.service.random_game(uid, number('Collection ID: '))
            game_id = game['game_id']
            print('Selected:', game['game_name'], f'(ID {game_id})')
        elif choice == 'i':
            game_id = number('Game ID: ')
        else:
            raise AppError('Choose i or r.')
        end_text = input('Completed session end (ISO UTC; blank = now): ').strip()
        end = timestamp(end_text) if end_text else datetime.now(timezone.utc).replace(microsecond=0)
        start_text = input('Session start (ISO UTC; blank = enter duration): ').strip()
        start = timestamp(start_text) if start_text else end - timedelta(seconds=number('Duration in seconds: '))
        self.service.record_play(uid, game_id, start, end)
        print('Play recorded:', hours_minutes((end - start).total_seconds()))

    def rate(self, uid):
        self.service.rate(uid, number('Game ID: '), number('Star rating 1-5: '))
        print('Your current rating was saved.')

    def social(self, uid):
        display(self.service.follows(uid))
        choice = input('[f]ind by email, [u]nfollow, [b]ack: ').strip().lower()
        if choice == 'b':
            return
        if choice == 'f':
            users = self.service.lookup_email(input('Email address: '))
            display(users)
            if users and input('Follow this user? Type yes: ').strip().lower() == 'yes':
                self.service.follow(uid, users[0]['uid'])
                print('Following.')
        elif choice == 'u':
            self.service.unfollow(uid, number('User ID to unfollow: '))
            print('Unfollowed.')
        else:
            raise AppError('Choose f, u, or b.')

    def platforms(self, uid):
        display(self.service.platforms())
        self.service.own_platform(uid, number('Platform ID to mark as owned: '))
        print('Platform ownership saved.')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Group 3 PostgreSQL video game database CLI')
    parser.add_argument('--config', type=Path, default=Path(__file__).resolve().parents[2] / 'dbInfo.ini')
    parser.add_argument('--check', action='store_true', help='Read-only connection and schema readiness check')
    args = parser.parse_args(argv)
    database = None
    try:
        settings = Settings.load(args.config)
        if not settings.password:
            settings = replace(settings, password=getpass(f'Database password for {settings.user}: '))
        database = connect(settings)
        if args.check:
            display([database.identity()])
        database.preflight()
        if args.check:
            print('Required tables, columns, and timestamp types are ready. No application data changed.')
        else:
            Console(Service(database)).run()
        return 0
    except (EOFError, KeyboardInterrupt):
        print('\nGoodbye.')
        return 0
    except (ValueError, OSError, psycopg.Error) as error:
        if isinstance(error, psycopg.OperationalError):
            print('Connection failed. Check the separate SSH tunnel and database login settings.')
            print(error.diag.message_primary or 'PostgreSQL could not be reached/authenticated.')
        else:
            action_error(error)
        return 1
    finally:
        if database is not None:
            database.close()
