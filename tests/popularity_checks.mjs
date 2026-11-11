// Optional PostgreSQL/WASM checks. These never connect to Starbug.
// Install: npm install --prefix tmp/pgtest --no-package-lock --ignore-scripts @electric-sql/pglite
// Run: .venv/Scripts/python tests/prepare_popularity_checks.py
// Then: node tests/popularity_checks.mjs
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import { PGlite } from '../tmp/pgtest/node_modules/@electric-sql/pglite/dist/index.js';

const captured = JSON.parse(await fs.readFile(new URL('../tmp/pgtest/popularity-query.json', import.meta.url), 'utf8'));
let position = 0;
const query = captured.query.replace(/%s/g, () => '$' + (++position));
const db = new PGlite();
const day = 86400;
const hour = 3600;
const cutoff = 90 * day;
let passed = 0;

async function games(rows) {
  for (const [id, name] of rows) {
    await db.query('INSERT INTO "Game"(game_id,game_name) VALUES ($1,$2)', [id, name]);
  }
}

async function play(gameId, uid, startSecondsAgo, endSecondsAgo) {
  await db.query(`INSERT INTO "Plays"(game_id,uid,start_time,end_time)
    VALUES ($1,$2,CURRENT_TIMESTAMP-($3 * INTERVAL '1 second'),
                  CURRENT_TIMESTAMP-($4 * INTERVAL '1 second'))`,
    [gameId, uid, startSecondsAgo, endSecondsAgo]);
}

async function ranked() {
  const result = await db.query(query, captured.params);
  return result.rows.map(row => ({...row, player_count:Number(row.player_count),
    capped_play_seconds:Number(row.capped_play_seconds)}));
}

async function check(name, test) {
  // CURRENT_TIMESTAMP is fixed within a transaction, so exact boundary checks are repeatable.
  await db.exec('BEGIN');
  try {
    await test();
    passed++;
    console.log('PASS:', name);
  } finally {
    await db.exec('ROLLBACK');
  }
}

try {
  await db.exec(`SET TIME ZONE 'UTC';
    CREATE TABLE "Game"(game_id INTEGER PRIMARY KEY,game_name TEXT NOT NULL);
    CREATE TABLE "Plays"(game_id INTEGER REFERENCES "Game",uid INTEGER NOT NULL,
      start_time TIMESTAMPTZ NOT NULL,end_time TIMESTAMPTZ,
      PRIMARY KEY(game_id,uid,start_time));`);

  await check('no activity returns no ranked games', async () => {
    await games([[1,'Unplayed']]);
    assert.deepEqual(await ranked(), []);
  });

  await check('distinct players outrank one heavy player', async () => {
    await games([[1,'Heavy Player'],[2,'Broad Reach']]);
    await play(1,1,201*hour,hour);
    await play(2,2,120,60);
    await play(2,3,120,60);
    assert.deepEqual(await ranked(), [
      {game_id:2,game_name:'Broad Reach',player_count:2,capped_play_seconds:120},
      {game_id:1,game_name:'Heavy Player',player_count:1,capped_play_seconds:20*hour},
    ]);
  });

  await check('repeat sessions are summed before the per-player cap', async () => {
    await games([[1,'Repeated Sessions'],[2,'Balanced Engagement']]);
    await play(1,1,30*hour,15*hour);
    await play(1,1,15*hour,0);
    await play(1,2,2*hour,hour);
    await play(2,3,13*hour,hour);
    await play(2,4,13*hour,hour);
    const rows = await ranked();
    assert.deepEqual(rows.map(r=>[r.game_id,r.player_count,r.capped_play_seconds]),
      [[2,2,24*hour],[1,2,21*hour]]);
  });

  await check('equal capped scores use name and ID, not uncapped playtime', async () => {
    await games([[1,'Zebra'],[2,'Alpha'],[3,'Alpha']]);
    await play(1,1,101*hour,hour);
    await play(2,2,21*hour,hour);
    await play(3,3,21*hour,hour);
    const rows = await ranked();
    assert.deepEqual(rows.map(r=>r.game_id), [2,3,1]);
    assert.ok(rows.every(r=>r.capped_play_seconds===20*hour));
  });

  await check('the cap applies independently to each game for the same player', async () => {
    await games([[1,'First Game'],[2,'Second Game']]);
    await play(1,1,31*hour,hour);
    await play(2,1,31*hour,hour);
    const rows = await ranked();
    assert.equal(rows.length,2);
    assert.ok(rows.every(r=>r.player_count===1 && r.capped_play_seconds===20*hour));
  });

  await check('rolling-window boundaries, partial sessions, and completed plays', async () => {
    await games(Array.from({length:9},(_,i)=>[i+1,'Boundary '+(i+1)]));
    await play(1,1,cutoff+hour,cutoff); // Ends exactly at cutoff: no time in window.
    await play(2,2,cutoff+hour,cutoff-1800); // Only the recent 30 minutes count.
    await play(3,3,cutoff,cutoff-1); // Starts exactly at cutoff: included.
    await play(4,4,60,0); // Ends exactly now: included.
    await play(5,5,hour,-hour); // Future end: not a completed session yet.
    await play(6,6,hour,null); // Unfinished sessions are excluded.
    await play(7,7,100,100); // Zero-duration sessions are excluded.
    await play(8,8,-60,-120); // Entirely in the future.
    await play(9,9,100,200); // Negative-duration sessions are excluded.
    assert.deepEqual((await ranked()).map(r=>[r.game_id,r.player_count,r.capped_play_seconds]),
      [[2,1,1800],[4,1,60],[3,1,1]]);
  });

  await check('older sessions do not consume the recent playtime allowance', async () => {
    await games([[1,'Recent Return'],[2,'Old Activity Only']]);
    await play(1,1,cutoff+201*hour,cutoff+hour);
    await play(1,1,2*hour,hour);
    await play(2,2,cutoff+201*hour,cutoff+hour);
    assert.deepEqual((await ranked()).map(r=>[r.game_id,r.player_count,r.capped_play_seconds]),
      [[1,1,hour]]);
  });

  await check('SQL returns at most twenty games in deterministic order', async () => {
    await games(Array.from({length:26},(_,i)=>[i+1,'Game '+String(i+1).padStart(2,'0')]));
    for (let id=1;id<=25;id++) await play(id,id,120,60);
    assert.deepEqual((await ranked()).map(r=>r.game_id), Array.from({length:20},(_,i)=>i+1));
  });

  console.log(`PASS: ${passed} isolated PostgreSQL popularity scenarios. Starbug was not changed.`);
} catch (error) {
  console.error('FAIL:',error.code ?? error.name,error.message);
  process.exitCode = 1;
} finally {
  await db.close();
}
