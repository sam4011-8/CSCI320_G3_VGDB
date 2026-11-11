// Optional isolated PostgreSQL checks; no Starbug connection or credentials.
// Install: npm install --prefix tmp/pgtest --no-package-lock --ignore-scripts @electric-sql/pglite
// Run: .venv/Scripts/python tests/prepare_release_checks.py
// Then: node tests/release_checks.mjs
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import { PGlite } from '../tmp/pgtest/node_modules/@electric-sql/pglite/dist/index.js';

const captured = JSON.parse(await fs.readFile(new URL('../tmp/pgtest/release-query.json', import.meta.url), 'utf8'));
let position = 0;
const query = captured.query.replace(/%s/g, () => '$' + (++position));
const db = new PGlite();
const hour = 3600;
let passed = 0;

async function game(id, name, releases) {
  await db.query('INSERT INTO "Game"(game_id,game_name) VALUES ($1,$2)', [id,name]);
  for (let i=0;i<releases.length;i++) {
    await db.query('INSERT INTO "OnPlatform"(game_id,platform_id,release_date) VALUES ($1,$2,$3)',
      [id,i+1,releases[i]]);
  }
}

async function play(gameId, uid, start, end) {
  await db.query('INSERT INTO "Plays"(game_id,uid,start_time,end_time) VALUES ($1,$2,$3,$4)',
    [gameId,uid,start,end]);
}

async function ranked(asOf='2026-11-15T12:00:00Z') {
  const result = await db.query(query, [asOf,...captured.params.slice(1)]);
  return result.rows.map(row=>({...row,
    release_date:row.release_date instanceof Date ? row.release_date.toISOString().slice(0,10) : row.release_date,
    player_count:Number(row.player_count),
    capped_play_seconds:Number(row.capped_play_seconds)}));
}

async function check(name, test) {
  await db.exec('BEGIN');
  try {
    await test();
    passed++;
    console.log('PASS:',name);
  } finally {
    await db.exec('ROLLBACK');
  }
}

try {
  await db.exec(`SET TIME ZONE 'UTC';
    CREATE TABLE "Game"(game_id INTEGER PRIMARY KEY,game_name TEXT NOT NULL);
    CREATE TABLE "OnPlatform"(game_id INTEGER REFERENCES "Game",platform_id INTEGER,
      release_date DATE NOT NULL,PRIMARY KEY(game_id,platform_id));
    CREATE TABLE "Plays"(game_id INTEGER REFERENCES "Game",uid INTEGER NOT NULL,
      start_time TIMESTAMPTZ NOT NULL,end_time TIMESTAMPTZ,
      PRIMARY KEY(game_id,uid,start_time));`);

  await check('an empty catalog returns no new releases', async () => {
    assert.deepEqual(await ranked(),[]);
  });

  await check('calendar-month filtering excludes old titles, new ports, and upcoming games', async () => {
    await game(1,'Old Game',['2026-10-31']);
    await game(2,'New Port',['2020-01-01','2026-11-10']);
    await game(3,'First Day',['2026-11-01','2026-11-10']);
    await game(4,'Released Today',['2026-11-15']);
    await game(5,'Upcoming This Month',['2026-11-16']);
    await game(6,'Next Month',['2026-12-01']);
    await game(7,'No Platform',[]);
    const rows = await ranked();
    assert.deepEqual(rows.map(r=>[r.game_id,String(r.release_date).slice(0,10)]),
      [[4,'2026-11-15'],[3,'2026-11-01']]);
    assert.ok(rows.every(r=>r.player_count===0 && r.capped_play_seconds===0));
  });

  await check('distinct players outrank one heavy player among monthly releases', async () => {
    await game(1,'Heavy Player',['2026-11-01']);
    await game(2,'Broad Reach',['2026-11-01']);
    await game(3,'No Plays Yet',['2026-11-14']);
    await play(1,1,'2026-11-01T00:00:00Z','2026-11-12T00:00:00Z');
    await play(2,2,'2026-11-10T00:00:00Z','2026-11-10T00:01:00Z');
    await play(2,3,'2026-11-10T00:00:00Z','2026-11-10T00:01:00Z');
    assert.deepEqual((await ranked()).map(r=>[r.game_id,r.player_count,r.capped_play_seconds]),
      [[2,2,120],[1,1,20*hour],[3,0,0]]);
  });

  await check('session totals are capped per player and duplicate platforms do not multiply time', async () => {
    await game(1,'Repeated Sessions',['2026-11-01','2026-11-02','2026-11-01']);
    await game(2,'Balanced Engagement',['2026-11-01']);
    await play(1,1,'2026-11-05T00:00:00Z','2026-11-05T15:00:00Z');
    await play(1,1,'2026-11-06T00:00:00Z','2026-11-06T15:00:00Z');
    await play(1,2,'2026-11-06T00:00:00Z','2026-11-06T01:00:00Z');
    await play(2,3,'2026-11-06T00:00:00Z','2026-11-06T12:00:00Z');
    await play(2,4,'2026-11-06T00:00:00Z','2026-11-06T12:00:00Z');
    assert.deepEqual((await ranked()).map(r=>[r.game_id,r.player_count,r.capped_play_seconds]),
      [[2,2,24*hour],[1,2,21*hour]]);
  });

  await check('scoring counts completed time after release and excludes future or unfinished sessions', async () => {
    await game(1,'Timing Checks',['2026-11-10']);
    await play(1,1,'2026-11-09T23:30:00Z','2026-11-10T00:30:00Z');
    await play(1,2,'2026-11-09T22:00:00Z','2026-11-10T00:00:00Z');
    await play(1,3,'2026-11-15T11:59:00Z','2026-11-15T12:00:00Z');
    await play(1,4,'2026-11-15T11:00:00Z','2026-11-15T13:00:00Z');
    await play(1,5,'2026-11-15T11:00:00Z',null);
    await play(1,6,'2026-11-15T11:00:00Z','2026-11-15T11:00:00Z');
    await play(1,7,'2026-10-01T00:00:00Z','2026-10-01T01:00:00Z');
    assert.deepEqual((await ranked()).map(r=>[r.player_count,r.capped_play_seconds]),[[2,1860]]);
  });

  await check('remaining ties use newest release, then name and game ID; limit is five', async () => {
    await game(1,'Zebra',['2026-11-02']);
    await game(2,'Alpha',['2026-11-03']);
    await game(3,'Alpha',['2026-11-03']);
    await game(4,'Newest',['2026-11-10']);
    await game(5,'Beta',['2026-11-03']);
    await game(6,'Oldest',['2026-11-01']);
    await game(7,'Another Old Game',['2026-11-01']);
    assert.deepEqual((await ranked()).map(r=>r.game_id),[4,2,3,5,1]);
  });

  await check('January uses the current calendar month across the year boundary', async () => {
    await game(1,'December Release',['2026-12-31']);
    await game(2,'New Year Release',['2027-01-01']);
    await game(3,'Tomorrow',['2027-01-02']);
    assert.deepEqual((await ranked('2027-01-01T12:00:00Z')).map(r=>r.game_id),[2]);
  });

  await check('leap-day releases qualify in February and next-month releases do not', async () => {
    await game(1,'Leap Day',['2028-02-29']);
    await game(2,'March Release',['2028-03-01']);
    assert.deepEqual((await ranked('2028-02-29T12:00:00Z')).map(r=>r.game_id),[1]);
  });

  await check('timezone-aware report dates use the application UTC calendar', async () => {
    await game(1,'February Release',['2027-02-28']);
    await game(2,'March Release',['2027-03-01']);
    assert.deepEqual((await ranked('2027-03-01T00:30:00+02:00')).map(r=>r.game_id),[1]);
  });

  await check('the default query uses the live database month when no report date is supplied', async () => {
    const today = (await db.query('SELECT CURRENT_DATE::TEXT AS today')).rows[0].today;
    await game(1,'Today Release',[today]);
    const rows = await ranked(null);
    assert.deepEqual(rows.map(r=>[r.game_id,r.player_count,r.capped_play_seconds]),[[1,0,0]]);
  });

  console.log(`PASS: ${passed} isolated PostgreSQL new-release scenarios. Starbug was not changed.`);
} catch (error) {
  console.error('FAIL:',error.code ?? error.name,error.message);
  process.exitCode = 1;
} finally {
  await db.close();
}
