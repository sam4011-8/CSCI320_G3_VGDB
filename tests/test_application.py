"""Fast behavior checks; PostgreSQL SQL/trigger checks live in postgres_checks.mjs."""
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import unittest
from unittest.mock import patch

from src.vgdb.db import Settings, SetupError, Database
from src.vgdb.security import hash_password, verify_password
from src.vgdb.service import AppError, SearchFilters, Service, hours_minutes, search_query


class FakeDB:
    def __init__(self, one=None, rows=None, rowcount=1):
        self.calls=[]
        self.answer=one
        self.results=rows or []
        self.rowcount=rowcount

    def transaction(self):
        return nullcontext()

    def one(self, query, params=None):
        self.calls.append((query,params))
        return self.answer

    def rows(self, query, params=None):
        self.calls.append((query,params))
        return self.results

    def run(self, query, params=None):
        self.calls.append((query,params))
        return self.rowcount


class ApplicationTests(unittest.TestCase):
    def test_password_hashes_have_fresh_salts_and_reject_wrong_or_fixture_passwords(self):
        first=hash_password('sample passphrase')
        second=hash_password('sample passphrase')
        self.assertNotEqual(first,second)
        self.assertTrue(first.startswith('$argon2id$'))
        self.assertTrue(verify_password(first,'sample passphrase'))
        self.assertFalse(verify_password(first,'wrong passphrase'))
        self.assertFalse(verify_password('$scrypt$synthetic-report-fixture','sample passphrase'))
        with self.assertRaises(ValueError):
            hash_password('short')

    def test_failed_login_never_writes_access(self):
        db=FakeDB(one={'uid':1,'username':'a','password_hash':hash_password('correct password')})
        with self.assertRaisesRegex(AppError,'Invalid username'):
            Service(db).login('a','wrong password')
        self.assertEqual(len(db.calls),1)

    def test_successful_login_records_access_and_returns_no_hash(self):
        db=FakeDB(one={'uid':1,'username':'a','password_hash':hash_password('correct password')})
        result=Service(db).login('a','correct password')
        self.assertEqual(result,{'uid':1,'username':'a'})
        self.assertIn('INSERT INTO "AccessDate"',db.calls[-1][0])

    def test_unowned_collection_cannot_add_or_remove_games(self):
        db=FakeDB(one=None)
        for method,args in [('add_game',(1,9,2,3)),('remove_game',(1,9,2))]:
            with self.assertRaisesRegex(AppError,'not found'):
                getattr(Service(db),method)(*args)
        self.assertTrue(all('SELECT collection_id' in query for query,_ in db.calls))

    def test_search_keeps_values_out_of_sql_and_whitelists_sort(self):
        term="x' OR TRUE --%_"
        query,params=search_query(SearchFilters(title=term),1,'price',True)
        self.assertNotIn(term,query)
        self.assertIn('offers.min_price DESC NULLS LAST',query)
        self.assertEqual(params['title'],"%x' OR TRUE --\\%\\_%")
        with self.assertRaises(AppError):
            search_query(SearchFilters(),1,'name; DROP TABLE anything')

    def test_repeated_sort_preserves_filter_values(self):
        filters=SearchFilters(title='Quest',platform=2,price_max=Decimal('35'))
        _,first=search_query(filters,1)
        _,second=search_query(filters,1,'genre',True)
        self.assertEqual(first,second)

    def test_search_rejects_invalid_ranges_and_nonfinite_prices(self):
        for filters in [SearchFilters(price_min=Decimal('NaN')),
                        SearchFilters(price_max=Decimal('Infinity')),
                        SearchFilters(price_min=Decimal('3'),price_max=Decimal('2'))]:
            with self.assertRaises(AppError):
                filters.validate()

    def test_invalid_play_times_never_reach_database(self):
        db=FakeDB()
        end=datetime.now(timezone.utc).replace(microsecond=0)-timedelta(seconds=2)
        cases=[(end,end),(end.replace(tzinfo=None),end),
               (end-timedelta(seconds=1),end+timedelta(days=1)),
               (end-timedelta(seconds=1,microseconds=1),end)]
        for start,stop in cases:
            with self.assertRaises(AppError):
                Service(db).record_play(1,2,start,stop)
        self.assertEqual(db.calls,[])

    def test_ratings_and_self_follow_validate_before_writes(self):
        db=FakeDB()
        for rating in [0,6,1.5,True]:
            with self.assertRaises(AppError):
                Service(db).rate(1,2,rating)
        with self.assertRaises(AppError):
            Service(db).follow(1,1)
        self.assertEqual(db.calls,[])

    def test_hours_minutes_can_exceed_one_day(self):
        self.assertEqual(hours_minutes(0),'0:00')
        self.assertEqual(hours_minutes(8100),'2:15')
        self.assertEqual(hours_minutes(90061),'25:01')

    @patch.dict(os.environ,{},clear=True)
    def test_config_does_not_interpolate_password_percent_signs(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'dbInfo.ini'
            path.write_text('[database]\nuser=test_login\npassword=synthetic%value\nport=15432\n',encoding='utf-8')
            settings=Settings.load(path)
            self.assertEqual(settings.password,'synthetic%value')
            self.assertEqual(settings.role,'p320_3')
            path.write_text('[database]\nport=99999\n',encoding='utf-8')
            with self.assertRaises(SetupError):
                Settings.load(path)

    def test_preflight_rejects_existing_incomplete_schema(self):
        db=Database(None,'p320_3')
        db.rows=lambda *args: [{'table_name':'AccessDate','column_name':'access_date','data_type':'integer'}]
        with self.assertRaises(SetupError) as error:
            db.preflight()
        self.assertIn('User.password_hash is missing',str(error.exception))
        self.assertIn('AccessDate.access_date must be TIMESTAMPTZ',str(error.exception))


if __name__=='__main__':
    unittest.main()
