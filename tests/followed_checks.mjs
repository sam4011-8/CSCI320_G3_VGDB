// Optional isolated PostgreSQL checks; no Starbug connection or credentials.
// Install: npm install --prefix tmp/pgtest --no-package-lock --ignore-scripts @electric-sql/pglite
// Run: .venv/Scripts/python tests/prepare_followed_checks.py
// Then: node tests/followed_checks.mjs
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import { PGlite } from '../tmp/pgtest/node_modules/@electric-sql/pglite/dist/index.js';

const captured = JSON.parse(await fs.readFile(new URL('../tmp/pgtest/followed-query.json', import.meta.url),'utf8'));
const db = new PGlite();
const hour = 3600;
const cutoff = 90 * 86400;
let passed = 0;

function positional(query) {
  let position = 0;
  return query.replace(/%s/g,()=>'$'+(++position));
}

async function games(rows) {
  for (const [id,name] of rows) {
    await db.query('INSERT INTO "Game"(game_id,game_name) VALUES ($1,$2)',[id,name]);
  }
}

async function follow(uid, followedId) {
  await db.query('INSERT INTO "Following"(uid,followed_id) VALUES ($1,$2)',[uid,followedId]);
}

async function play(gameId, uid, startSecondsAgo, endSecondsAgo) {
  await db.query(`INSERT INTO "Plays"(game_id,uid,start_time,end_time)
    VALUES ($1,$2,CURRENT_TIMESTAMP-($3 * INTERVAL '1 second'),
                  CURRENT_TIMESTAMP-($4 * INTERVAL '1 second'))`,
    [gameId,uid,startSecondsAgo,endSecondsAgo]);
}

async function ranked(uid=1) {
  const params = [...captured.followed.params];
  params[1] = uid;
  const result = await db.query(positional(captured.followed.query),params);
  return result.rows.map(row=>({...row,player_count:Number(row.player_count),
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
    CREATE TABLE "Following"(uid INTEGER,followed_id INTEGER,
      PRIMARY KEY(uid,followed_id),CHECK(uid<>followed_id));
    CREATE TABLE "Plays"(game_id INTEGER REFERENCES "Game",uid INTEGER NOT NULL,
      start_time TIMESTAMPTZ NOT NULL,end_time TIMESTAMPTZ,
      PRIMARY KEY(game_id,uid,start_time));`);

  await check('no follows returns an empty list while global popularity still includes activity',async()=>{
    await games([[1,'Global Only']]);
    await follow(2,3);
    await play(1,3,120,60);
    assert.deepEqual(await ranked(1),[]);
    const global = await db.query(positional(captured.global.query),captured.global.params);
    assert.deepEqual(global.rows.map(r=>r.game_id),[1]);
  });

  await check('counts direct follows, excluding outsiders, the viewer, incoming followers, and indirect follows',async()=>{
    await games([[1,'Direct Follow'],[2,'Outsider'],[3,'Viewer'],[4,'Incoming Follower'],[5,'Indirect Follow']]);
    await follow(1,2);
    await follow(3,4);
    await follow(4,1);
    await follow(2,5);
    await play(1,2,120,60);
    await play(2,3,201*hour,hour);
    await play(3,1,201*hour,hour);
    await play(4,4,201*hour,hour);
    await play(5,5,201*hour,hour);
    assert.deepEqual((await ranked(1)).map(r=>[r.game_id,r.player_count,r.capped_play_seconds]),[[1,1,60]]);
    assert.deepEqual((await ranked(4)).map(r=>r.game_id),[3]);
    assert.deepEqual((await ranked(2)).map(r=>r.game_id),[5]);
  });

  await check('distinct followed players rank first and outsiders never inflate the scores',async()=>{
    await games([[1,'Broad Followed Reach'],[2,'One Followed Player'],[3,'Outsiders Only']]);
    await follow(1,2);
    await follow(1,3);
    await play(1,2,201*hour,hour);
    await play(1,3,120,60);
    await play(2,2,31*hour,hour);
    for (let uid=4;uid<=10;uid++) {
      await play(2,uid,201*hour,hour);
      await play(3,uid,201*hour,hour);
    }
    assert.deepEqual((await ranked()).map(r=>[r.game_id,r.player_count,r.capped_play_seconds]),
      [[1,2,20*hour+60],[2,1,20*hour]]);
  });

  await check('sums repeated sessions before capping each followed player per game',async()=>{
    await games([[1,'Repeated Sessions'],[2,'Balanced Engagement']]);
    for (const uid of [2,3,4,5]) await follow(1,uid);
    await play(1,2,30*hour,15*hour);
    await play(1,2,15*hour,0);
    await play(1,3,2*hour,hour);
    await play(2,4,13*hour,hour);
    await play(2,5,13*hour,hour);
    assert.deepEqual((await ranked()).map(r=>[r.game_id,r.player_count,r.capped_play_seconds]),
      [[2,2,24*hour],[1,2,21*hour]]);
  });

  await check('follow and unfollow changes are reflected on the next query',async()=>{
    await games([[1,'First Circle'],[2,'New Follow']]);
    await follow(1,2);
    await follow(1,3);
    await play(1,2,120,60);
    await play(1,3,120,60);
    await play(2,4,2*hour,hour);
    assert.deepEqual((await ranked()).map(r=>[r.game_id,r.player_count]),[[1,2]]);
    await db.query('DELETE FROM "Following" WHERE uid=$1 AND followed_id=$2',[1,2]);
    assert.deepEqual((await ranked()).map(r=>[r.game_id,r.player_count,r.capped_play_seconds]),[[1,1,60]]);
    await follow(1,4);
    assert.deepEqual((await ranked()).map(r=>r.game_id),[2,1]);
  });

  await check('uses the rolling window, clips crossing sessions, and excludes unfinished or future plays',async()=>{
    await games(Array.from({length:7},(_,i)=>[i+1,'Boundary '+(i+1)]));
    await follow(1,2);
    await play(1,2,cutoff+hour,cutoff);
    await play(2,2,cutoff+hour,cutoff-1800);
    await play(3,2,hour,-hour);
    await play(4,2,hour,null);
    await play(5,2,100,100);
    await play(6,2,60,0);
    await play(7,2,cutoff,cutoff-1);
    assert.deepEqual((await ranked()).map(r=>[r.game_id,r.player_count,r.capped_play_seconds]),
      [[2,1,1800],[6,1,60],[7,1,1]]);
  });

  await check('returns at most twenty games with no outsider-only entries',async()=>{
    await games(Array.from({length:26},(_,i)=>[i+1,'Game '+String(i+1).padStart(2,'0')]));
    await follow(1,2);
    for (let id=1;id<=25;id++) await play(id,2,120,60);
    await play(26,3,201*hour,hour);
    assert.deepEqual((await ranked()).map(r=>r.game_id),Array.from({length:20},(_,i)=>i+1));
  });

  await check('equal capped totals use name and ID with a separate allowance for each game',async()=>{
    await games([[1,'Zebra'],[2,'Alpha'],[3,'Alpha']]);
    await follow(1,2);
    await follow(1,3);
    await play(1,2,101*hour,hour);
    await play(2,3,21*hour,hour);
    await play(3,2,21*hour,hour);
    const rows = await ranked();
    assert.deepEqual(rows.map(r=>r.game_id),[2,3,1]);
    assert.ok(rows.every(r=>r.player_count===1 && r.capped_play_seconds===20*hour));
  });

  await check('followed accounts with no recent completed plays produce no results',async()=>{
    await games([[1,'Old Followed Play'],[2,'Unfollowed Activity']]);
    await follow(1,2);
    await play(1,2,cutoff+hour,cutoff);
    await play(2,3,120,60);
    assert.deepEqual(await ranked(),[]);
  });

  console.log(`PASS: ${passed} isolated PostgreSQL followed-user scenarios. Starbug was not changed.`);
} catch (error) {
  console.error('FAIL:',error.code ?? error.name,error.message);
  process.exitCode = 1;
} finally {
  await db.close();
}
