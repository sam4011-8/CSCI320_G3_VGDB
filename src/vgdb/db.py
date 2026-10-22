"""Connection configuration and explicit SQL access. No ORM or automatic DDL."""
from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path
import os

import psycopg
from psycopg import sql
from psycopg.rows import dict_row


class SetupError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    host: str = '127.0.0.1'
    port: int = 15432
    dbname: str = 'p320_3'
    user: str = ''
    role: str = 'p320_3'
    schema: str = 'p320_3'
    password: str = ''

    @classmethod
    def load(cls, path):
        parser = ConfigParser(interpolation=None)
        path = Path(path)
        if path.exists():
            with path.open(encoding='utf-8') as source:
                parser.read_file(source)
        section = parser['database'] if parser.has_section('database') else {}
        defaults = cls()
        env_names = {'host': 'PGHOST', 'port': 'PGPORT', 'dbname': 'PGDATABASE',
                     'user': 'PGUSER', 'password': 'PGPASSWORD',
                     'role': 'VGDB_ROLE', 'schema': 'VGDB_SCHEMA'}
        values = {key: os.environ.get(env, section.get(key, getattr(defaults, key)))
                  for key, env in env_names.items()}
        try:
            values['port'] = int(values['port'])
        except (ValueError, TypeError) as error:
            raise SetupError('Database port must be an integer.') from error
        if not 1 <= values['port'] <= 65535:
            raise SetupError('Database port must be between 1 and 65535.')
        if any(not values[key] for key in ('host', 'dbname', 'user', 'schema')):
            raise SetupError('Database host, dbname, user, and schema are required. '
                             'Set your CS username in dbInfo.ini or PGUSER.')
        return cls(**values)


REQUIRED_COLUMNS = {
    'User': {'uid', 'username', 'email', 'first_name', 'last_name', 'creation_date', 'password_hash'},
    'Game': {'game_id', 'game_name', 'esrb_rating'},
    'AccessDate': {'uid', 'access_date'},
    'collection': {'uid', 'collectionid', 'collection_name'},
    'contributor': {'contributorid', 'contributor_name'},
    'following': {'uid', 'followed_id'},
    'genre': {'genre_id', 'genre_name'},
    'genreclassification': {'game_id', 'genre_id'},
    'platform': {'platformid', 'platform_name'},
    'rating': {'uid', 'game_id', 'rating'},
    'plays': {'uid', 'game_id', 'start_time', 'end_time'},
    'onplatform': {'game_id', 'platformid', 'release_date', 'price'},
    'platformsowned': {'uid', 'platformid'},
    'collectionitem': {'collectionid', 'game_id'},
    'developed': {'contributorid', 'game_id'},
    'published': {'contributorid', 'game_id'},
}


def connect(settings):
    conn = psycopg.connect(host=settings.host, port=settings.port, dbname=settings.dbname,
                           user=settings.user, password=settings.password or None,
                           connect_timeout=10, autocommit=True, row_factory=dict_row)
    try:
        if settings.role:
            conn.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(settings.role)))
        conn.execute(sql.SQL('SET search_path TO {}, pg_catalog').format(sql.Identifier(settings.schema)))
        conn.execute("SET TIME ZONE 'UTC'")
        conn.execute("SET statement_timeout = '30s'")
        return Database(conn, settings.schema)
    except BaseException:
        conn.close()
        raise


class Database:
    def __init__(self, connection, schema):
        self.connection = connection
        self.schema = schema

    def rows(self, query, params=None):
        with self.connection.execute(query, params) as cursor:
            return cursor.fetchall()

    def one(self, query, params=None):
        with self.connection.execute(query, params) as cursor:
            return cursor.fetchone()

    def run(self, query, params=None):
        with self.connection.execute(query, params) as cursor:
            return cursor.rowcount

    def transaction(self):
        return self.connection.transaction()

    def close(self):
        self.connection.close()

    def identity(self):
        return self.one('SELECT current_database() AS database, session_user AS login_role, '
                        'current_user AS active_role, current_schema() AS schema, '
                        "current_setting('server_version') AS version")

    def preflight(self):
        columns = self.rows('SELECT table_name, column_name, data_type FROM information_schema.columns '
                            'WHERE table_schema = %s', (self.schema,))
        actual = {(row['table_name'], row['column_name']): row['data_type'] for row in columns}
        issues = [f'{table}.{column} is missing' for table, names in REQUIRED_COLUMNS.items()
                  for column in sorted(names) if (table, column) not in actual]
        for table, column in [('AccessDate', 'access_date'), ('User', 'creation_date'),
                              ('plays', 'start_time'), ('plays', 'end_time')]:
            if (table, column) in actual and actual[table, column] != 'timestamp with time zone':
                issues.append(f'{table}.{column} must be TIMESTAMPTZ')
        if issues:
            raise SetupError('Schema is not ready:\n  ' + '\n  '.join(issues) +
                             '\nAsk the team maintainer to verify the shared schema. '
                             'This application never runs DDL automatically.')
