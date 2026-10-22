"""Interactive Phase 2 CLI. SQL schema installation is always a separate action."""
import argparse
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from getpass import getpass
from pathlib import Path

import psycopg

from .db import Settings, SetupError, connect
from .service import AppError, SearchFilters, Service, hours_minutes


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
                choice = input('\n[c]ollections [g]ames [p]lay [r]ate [s]ocial '
                               '[o]wned platforms [l]ogout [q]uit: ').strip().lower()
                if choice == 'q':
                    return
                if choice == 'l':
                    break
                actions = {'c': self.collections, 'g': self.games, 'p': self.play,
                           'r': self.rate, 's': self.social, 'o': self.platforms}
                if choice not in actions:
                    print('Choose one of the listed letters.')
                    continue
                try:
                    actions[choice](user['uid'])
                except (ValueError, psycopg.Error) as error:
                    action_error(error)

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
                    print('Created:', self.service.create_collection(uid, input('Collection name: '))['collectionid'])
                elif choice == 'e':
                    self.service.rename_collection(uid, number('Collection ID: '), input('New name: '))
                    print('Renamed.')
                elif choice == 'd':
                    collectionid = number('Collection ID: ')
                    if input('Delete this collection and its memberships? Type yes: ').strip().lower() == 'yes':
                        self.service.delete_collection(uid, collectionid)
                        print('Deleted.')
                elif choice == 'a':
                    collectionid, game_id = number('Collection ID: '), number('Game ID: ')
                    display(self.service.platforms())
                    owned = self.service.add_game(uid, collectionid, game_id, number('Selected platform ID: '))
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
