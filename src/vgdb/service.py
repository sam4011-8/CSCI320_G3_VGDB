"""Application operations with explicit parameterized PostgreSQL queries."""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from decimal import Decimal
import re

from .security import hash_password, verify_password, hasher


class AppError(ValueError):
    pass


def required(value, label):
    value = value.strip()
    if not value:
        raise AppError(f'{label} is required.')
    return value


def hours_minutes(seconds):
    minutes = int(seconds) // 60
    return f'{minutes // 60}:{minutes % 60:02d}'


def literal_pattern(value):
    return '%' + value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


@dataclass(frozen=True)
class SearchFilters:
    title: str = ''
    developer: str = ''
    platform: int | None = None
    genre: int | None = None
    date_from: object = None
    date_to: object = None
    price_min: Decimal | None = None
    price_max: Decimal | None = None

    def validate(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise AppError('The release-date range is reversed.')
        for price in (self.price_min, self.price_max):
            if price is not None and (not price.is_finite() or price < 0):
                raise AppError('Prices must be finite, nonnegative amounts.')
        if self.price_min is not None and self.price_max is not None and self.price_min > self.price_max:
            raise AppError('The price range is reversed.')


SORTS = {'name': 'g.game_name', 'price': 'offers.min_price',
         'genre': 'categories.first_genre', 'year': 'EXTRACT(YEAR FROM offers.release_date)'}


def search_query(filters, uid, sort='default', descending=False, offset=0):
    filters.validate()
    if sort != 'default' and sort not in SORTS:
        raise AppError('Sort by name, price, genre, or year.')
    if offset < 0:
        raise AppError('Page offset cannot be negative.')
    params = asdict(filters) | {'uid': uid, 'limit': 50, 'offset': offset}
    conditions = []
    for field, expression in [('title', 'g.game_name'), ('developer', 'c.contributor_name')]:
        if params[field]:
            params[field] = literal_pattern(params[field])
            if field == 'title':
                conditions.append(f'{expression} ILIKE %({field})s')
            else:
                conditions.append('EXISTS (SELECT 1 FROM Developed d JOIN Contributor c USING (contributor_id) '
                                  f'WHERE d.game_id=g.game_id AND {expression} ILIKE %({field})s)')
    if filters.genre is not None:
        conditions.append('EXISTS (SELECT 1 FROM GenreClassification gc '
                          'WHERE gc.game_id=g.game_id AND gc.genre_id=%(genre)s)')
    offer_conditions = []
    for field, expression in [('platform', 'op.platformid ='), ('date_from', 'op.release_date >='),
                              ('date_to', 'op.release_date <='), ('price_min', 'op.price >='),
                              ('price_max', 'op.price <=')]:
        if params[field] is not None:
            offer_conditions.append(f'{expression} %({field})s')
    if offer_conditions:
        conditions.append('EXISTS (SELECT 1 FROM OnPlatform op WHERE op.game_id=g.game_id AND ' +
                          ' AND '.join(offer_conditions) + ')')
    where = ' AND '.join(conditions) if conditions else 'TRUE'
    if sort == 'default':
        ordering = 'g.game_name ASC, offers.release_date ASC, g.game_id ASC'
    else:
        direction = 'DESC' if descending else 'ASC'
        ordering = f'{SORTS[sort]} {direction} NULLS LAST, g.game_name ASC, g.game_id ASC'
    query = '''
SELECT g.game_id, g.game_name, g.esrb_rating, offers.platforms,
       offers.release_date, offers.min_price, dev.names AS developers, pub.names AS publishers,
       categories.genres, COALESCE(played.seconds,0)::BIGINT AS play_seconds,
       stars.average_rating, stars.my_rating
FROM "Game" g
LEFT JOIN LATERAL (
    SELECT string_agg(DISTINCT p.platform_name, ', ' ORDER BY p.platform_name) AS platforms,
           MIN(op.release_date) AS release_date, MIN(op.price) AS min_price
    FROM "OnPlatform" op JOIN "Platform" p USING (platform_id) WHERE op.game_id=g.game_id
) offers ON TRUE
LEFT JOIN LATERAL (
    SELECT string_agg(DISTINCT c.contributor_name, ', ' ORDER BY c.contributor_name) AS names
    FROM "Developed" d JOIN "Contributor" c USING (contributor_id) WHERE d.game_id=g.game_id
) dev ON TRUE
LEFT JOIN LATERAL (
    SELECT string_agg(DISTINCT c.contributor_name, ', ' ORDER BY c.contributor_name) AS names
    FROM "Published" p JOIN "Contributor" c USING (contributor_id) WHERE p.game_id=g.game_id
) pub ON TRUE
LEFT JOIN LATERAL (
    SELECT string_agg(DISTINCT ge.genre_name, ', ' ORDER BY ge.genre_name) AS genres,
           MIN(ge.genre_name) AS first_genre
    FROM "GenreClassification" gc JOIN "Genre" ge USING (genre_id) WHERE gc.game_id=g.game_id
) categories ON TRUE
LEFT JOIN LATERAL (
    SELECT SUM(EXTRACT(EPOCH FROM (end_time-start_time))) AS seconds
    FROM "Plays" WHERE game_id=g.game_id AND uid=%(uid)s
) played ON TRUE
LEFT JOIN LATERAL (
    SELECT ROUND(AVG(rating),2) AS average_rating,
           MAX(rating) FILTER (WHERE uid=%(uid)s) AS my_rating
    FROM "Rating" WHERE game_id=g.game_id
) stars ON TRUE
WHERE ''' + where + ' ORDER BY ' + ordering + ' LIMIT %(limit)s OFFSET %(offset)s'
    return query, params


class Service:
    def __init__(self, database):
        self.db = database

    def register(self, username, password, first_name, last_name, email):
        username = required(username, 'Username')
        first_name, last_name = required(first_name, 'First name'), required(last_name, 'Last name')
        email = required(email, 'Email')
        if not re.fullmatch(r'[^@\s]+@[^@\s]+', email):
            raise AppError('Email must contain a nonempty local part and domain.')
        encoded = hash_password(password)
        with self.db.transaction():
            return self.db.one('INSERT INTO "User" (username,password_hash,first_name,last_name,email) '
                               'VALUES (%s,%s,%s,%s,%s) RETURNING uid,username',
                               (username, encoded, first_name, last_name, email))

    def login(self, username, password):
        with self.db.transaction():
            user = self.db.one('SELECT uid,username,password_hash FROM "User" WHERE lower(username)=lower(%s)',
                               (username.strip(),))
            if not user or not verify_password(user['password_hash'], password):
                raise AppError('Invalid username or password.')
            if hasher.check_needs_rehash(user['password_hash']):
                self.db.run('UPDATE "User" SET password_hash = %s WHERE uid=%s',
                            (hasher.hash(password), user['uid']))
            self.db.run('INSERT INTO "AccessDate" (uid,access_date) VALUES (%s,clock_timestamp())', (user['uid'],))
            return {'uid': user['uid'], 'username': user['username']}

    def collections(self, uid):
        return self.db.rows('''
WITH times AS (
    SELECT game_id,SUM(EXTRACT(EPOCH FROM (end_time-start_time))) AS seconds
    FROM "Plays" WHERE uid=%s GROUP BY game_id
)
SELECT c.collection_id,c.collection_name,COUNT(ci.game_id) AS game_count,
       COALESCE(SUM(t.seconds),0)::BIGINT AS total_seconds
FROM "Collection" c LEFT JOIN "CollectionItem" ci USING (collection_id)
LEFT JOIN times t ON t.game_id=ci.game_id WHERE c.uid=%s
GROUP BY c.collection_id,c.collection_name ORDER BY c.collection_name,c.collection_id''', (uid, uid))

    def create_collection(self, uid, name):
        with self.db.transaction():
            return self.db.one('INSERT INTO "Collection" (uid,collection_name) VALUES (%s,%s) '
                               'RETURNING collection_id', (uid, required(name, 'Collection name')))

    def _owned(self, uid, collection_id):
        if not self.db.one('SELECT collection_id FROM "Collection" WHERE uid=%s AND collection_id=%s FOR UPDATE',
                           (uid, collection_id)):
            raise AppError('Collection not found in your account.')

    def rename_collection(self, uid, collection_id, name):
        with self.db.transaction():
            if not self.db.run('UPDATE "Collection" SET collection_name = %s WHERE uid=%s AND collection_id=%s',
                               (required(name, 'Collection name'), uid, collection_id)):
                raise AppError('Collection not found in your account.')

    def delete_collection(self, uid, collection_id):
        with self.db.transaction():
            if not self.db.run('DELETE FROM "Collection" WHERE uid=%s AND collection_id=%s', (uid, collection_id)):
                raise AppError('Collection not found in your account.')

    def add_game(self, uid, collection_id, game_id, platform_id):
        with self.db.transaction():
            self._owned(uid, collection_id)
            offer = self.db.one('SELECT EXISTS (SELECT 1 FROM "PlatformsOwned" WHERE uid=%s AND platform_id=%s) '
                                'AS owned FROM "OnPlatform" WHERE game_id=%s AND platform_id=%s',
                                (uid, platform_id, game_id, platform_id))
            if not offer:
                raise AppError('That game is not available on the selected platform.')
            self.db.run('INSERT INTO "CollectionItem" (collection_id,game_id) VALUES (%s,%s)', (collection_id, game_id))
            return offer['owned']

    def remove_game(self, uid, collection_id, game_id):
        with self.db.transaction():
            self._owned(uid, collection_id)
            if not self.db.run('DELETE FROM "CollectionItem" WHERE collection_id=%s AND game_id=%s',
                               (collection_id, game_id)):
                raise AppError('Game is not in that collection.')

    def random_game(self, uid, collection_id):
        game = self.db.one('SELECT g.game_id,g.game_name FROM "Collection" c '
                           'JOIN "CollectionItem" ci USING (collection_id) JOIN "Game" g USING (game_id) '
                           'WHERE c.uid=%s AND c.collection_id=%s ORDER BY random() LIMIT 1', (uid, collection_id))
        if not game:
            raise AppError('Collection is empty or not in your account.')
        return game

    def record_play(self, uid, game_id, start, end):
        for value in (start, end):
            if value.tzinfo is None or value.utcoffset() is None:
                raise AppError('Play timestamps must include a timezone.')
            if value.microsecond:
                raise AppError('Record plays to whole-second precision.')
        if end <= start or end > datetime.now(timezone.utc):
            raise AppError('Record a completed session with an end after its start and no later than now.')
        with self.db.transaction():
            self.db.run('INSERT INTO "Plays" (uid,game_id,start_time,end_time) VALUES (%s,%s,%s,%s)',
                        (uid, game_id, start, end))

    def rate(self, uid, game_id, rating):
        if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
            raise AppError('Choose an integer star rating from 1 to 5.')
        with self.db.transaction():
            self.db.run('INSERT INTO "Rating" (uid,game_id,rating) VALUES (%s,%s,%s) '
                        'ON CONFLICT (uid,game_id) DO UPDATE SET rating=EXCLUDED.rating', (uid, game_id, rating))

    def search(self, uid, filters, sort='default', descending=False, offset=0):
        query, params = search_query(filters, uid, sort, descending, offset)
        return self.db.rows(query, params)

    def lookup_email(self, email):
        return self.db.rows('SELECT uid,username,email FROM "User" WHERE lower(email)=lower(%s)', (email.strip(),))

    def follows(self, uid):
        return self.db.rows('SELECT u.uid,u.username,u.email FROM "Following" f '
                            'JOIN "User" u ON u.uid=f.followed_id WHERE f.uid=%s ORDER BY u.username,u.uid', (uid,))

    def follow(self, uid, followed_id):
        if uid == followed_id:
            raise AppError('You cannot follow yourself.')
        with self.db.transaction():
            self.db.run('INSERT INTO "Following" (uid,followed_id) VALUES (%s,%s)', (uid, followed_id))

    def unfollow(self, uid, followed_id):
        with self.db.transaction():
            if not self.db.run('DELETE FROM "Following" WHERE uid=%s AND followed_id=%s', (uid, followed_id)):
                raise AppError('You are not following that user.')

    def platforms(self):
        return self.db.rows('SELECT platform_id,platform_name FROM "Platform" ORDER BY platform_name')

    def genres(self):
        return self.db.rows('SELECT genre_id,genre_name FROM "Genre" ORDER BY genre_name')

    def own_platform(self, uid, platform_id):
        with self.db.transaction():
            self.db.run('INSERT INTO "PlatformsOwned" (uid,platform_id) VALUES (%s,%s) ON CONFLICT DO NOTHING',
                        (uid, platform_id))
