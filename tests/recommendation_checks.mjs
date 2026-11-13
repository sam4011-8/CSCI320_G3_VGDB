// Optional isolated PostgreSQL checks. Never connects to Starbug.
// Install: npm install --prefix tmp/pgtest --no-package-lock --ignore-scripts @electric-sql/pglite
// Run: .venv/Scripts/python tests/prepare_recommendation_checks.py
// Then: node tests/recommendation_checks.mjs (add --scale for a larger synthetic workload).
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import { PGlite } from '../tmp/pgtest/node_modules/@electric-sql/pglite/dist/index.js';

const captured = JSON.parse(await fs.readFile(new URL('../tmp/pgtest/recommendation-query.json', import.meta.url),'utf8'));
const db = new PGlite();
const hour = 3600;
let passed = 0;

function bind(params) {
  const values = [];
  const positions = new Map();
  const query = captured.query.replace(/%\(([^)]+)\)s/g,(_,key)=>{
    if (!positions.has(key)) {
      values.push(params[key]);
      positions.set(key,values.length);
    }
    return '$'+positions.get(key);
  });
  return [query,values];
}

async function recommendations(uid=1) {
  const result = await db.query(...bind({...captured.params,uid}));
  return result.rows.map(row=>{
    const output = {...row};
    for (const key of ['preference_score','similar_player_score','score','similar_player_count',
                       'followed_player_count','recent_player_count','capped_recent_seconds']) {
      output[key] = Number(output[key]);
    }
    return output;
  });
}

async function game(id, name, options={}) {
  const {genres=[1],developers=[1],publishers=[5],platforms=[1],release='2020-01-01'} = options;
  await db.query('INSERT INTO "Game"(game_id,game_name) VALUES ($1,$2)',[id,name]);
  for (const platform of platforms) {
    await db.query('INSERT INTO "OnPlatform"(game_id,platform_id,release_date) VALUES ($1,$2,$3)',
      [id,platform,release]);
  }
  for (const [table,column,ids] of [['GenreClassification','genre_id',genres],
      ['Developed','contributor_id',developers],['Published','contributor_id',publishers]]) {
    for (const feature of ids) {
      await db.query(`INSERT INTO "${table}"(game_id,${column}) VALUES ($1,$2)`,[id,feature]);
    }
  }
}

async function play(gameId, uid, hours=1, endHoursAgo=1) {
  await db.query(`INSERT INTO "Plays"(game_id,uid,start_time,end_time)
    VALUES ($1,$2,CURRENT_TIMESTAMP-($3 * INTERVAL '1 hour'),
                  CURRENT_TIMESTAMP-($4 * INTERVAL '1 hour'))`,
    [gameId,uid,hours+endHoursAgo,endHoursAgo]);
}

async function rate(uid, gameId, rating) {
  await db.query('INSERT INTO "Rating"(uid,game_id,rating) VALUES ($1,$2,$3)',[uid,gameId,rating]);
}

async function own(uid, platform) {
  await db.query('INSERT INTO "PlatformsOwned"(uid,platform_id) VALUES ($1,$2)',[uid,platform]);
}

async function follow(uid, followedId) {
  await db.query('INSERT INTO "Following"(uid,followed_id) VALUES ($1,$2)',[uid,followedId]);
}

async function check(name, test) {
  await db.exec('BEGIN');
  try {
    await db.exec(`INSERT INTO "User"(uid) SELECT n FROM generate_series(1,60) n;
      INSERT INTO "Platform" VALUES (1,'PC'),(2,'PlayStation'),(3,'Switch');
      INSERT INTO "Genre" VALUES (1,'RPG'),(2,'Racing'),(3,'Puzzle'),(4,'Adventure'),(5,'Strategy');
      INSERT INTO "Contributor" VALUES (1,'Studio A'),(2,'Studio B'),(3,'Studio C'),
        (4,'Studio D'),(5,'Publisher X'),(6,'Publisher Y');`);
    await test();
    passed++;
    console.log('PASS:',name);
  } finally {
    await db.exec('ROLLBACK');
  }
}

function close(actual, expected, message) {
  assert.ok(Math.abs(actual-expected)<1e-8,`${message ?? 'score'}: ${actual} != ${expected}`);
}

try {
  await db.exec(`SET TIME ZONE 'UTC';
    CREATE TABLE "User"(uid INTEGER PRIMARY KEY);
    CREATE TABLE "Game"(game_id INTEGER PRIMARY KEY,game_name TEXT NOT NULL);
    CREATE TABLE "Platform"(platform_id INTEGER PRIMARY KEY,platform_name TEXT NOT NULL);
    CREATE TABLE "OnPlatform"(game_id INTEGER REFERENCES "Game",platform_id INTEGER REFERENCES "Platform",
      release_date DATE NOT NULL,PRIMARY KEY(game_id,platform_id));
    CREATE TABLE "PlatformsOwned"(uid INTEGER REFERENCES "User",platform_id INTEGER REFERENCES "Platform",
      PRIMARY KEY(uid,platform_id));
    CREATE TABLE "Genre"(genre_id INTEGER PRIMARY KEY,genre_name TEXT NOT NULL);
    CREATE TABLE "GenreClassification"(game_id INTEGER REFERENCES "Game",genre_id INTEGER REFERENCES "Genre",
      PRIMARY KEY(game_id,genre_id));
    CREATE TABLE "Contributor"(contributor_id INTEGER PRIMARY KEY,contributor_name TEXT NOT NULL);
    CREATE TABLE "Developed"(game_id INTEGER REFERENCES "Game",contributor_id INTEGER REFERENCES "Contributor",
      PRIMARY KEY(game_id,contributor_id));
    CREATE TABLE "Published"(game_id INTEGER REFERENCES "Game",contributor_id INTEGER REFERENCES "Contributor",
      PRIMARY KEY(game_id,contributor_id));
    CREATE TABLE "Plays"(game_id INTEGER REFERENCES "Game",uid INTEGER REFERENCES "User",
      start_time TIMESTAMPTZ NOT NULL,end_time TIMESTAMPTZ,PRIMARY KEY(game_id,uid,start_time));
    CREATE TABLE "Rating"(uid INTEGER REFERENCES "User",game_id INTEGER REFERENCES "Game",
      rating INTEGER CHECK(rating BETWEEN 1 AND 5),PRIMARY KEY(uid,game_id));
    CREATE TABLE "Following"(uid INTEGER REFERENCES "User",followed_id INTEGER REFERENCES "User",
      PRIMARY KEY(uid,followed_id),CHECK(uid<>followed_id));`);

  await check('empty catalogs and missing accounts return no recommendations',async()=>{
    assert.deepEqual(await recommendations(),[]);
    await game(1,'Available');
    assert.deepEqual(await recommendations(999),[]);
  });

  await check('new users without platforms get global popular picks using distinct players and caps',async()=>{
    await game(1,'Heavy Player');
    await game(2,'Broad Reach',{platforms:[2]});
    await play(1,2,200);
    await play(2,3,1);
    await play(2,4,1);
    const rows = await recommendations();
    assert.deepEqual(rows.map(r=>r.game_id),[2,1]);
    assert.ok(rows.every(r=>r.source==='popular' && !r.platform_filtered && r.score===0));
    assert.equal(rows[1].capped_recent_seconds,20*hour);
  });

  await check('platform filtering happens before limiting and accepts games on any owned platform',async()=>{
    await own(1,1);
    await own(1,3);
    await game(1,'PlayStation Only',{platforms:[2]});
    for (let uid=2;uid<=20;uid++) await play(1,uid,1);
    await game(2,'Cross Platform',{platforms:[1,2]});
    await game(3,'Switch Game',{platforms:[3]});
    await game(4,'Future Game',{release:'2099-01-01'});
    await game(5,'PC Port Not Released',{platforms:[2]});
    await db.query('INSERT INTO "OnPlatform" VALUES ($1,$2,$3)',[5,1,'2099-01-01']);
    await play(2,2,1);
    await play(3,3,1);
    const rows = await recommendations();
    assert.deepEqual(rows.map(r=>r.game_id),[2,3]);
    assert.deepEqual(rows.map(r=>r.platforms),['PC','Switch']);
    assert.ok(rows.every(r=>r.platform_filtered && r.source==='popular'));
  });

  await check('no history or recent popularity is honestly labeled as available catalog games',async()=>{
    await game(1,'Available');
    const rows = await recommendations();
    assert.equal(rows[0].source,'catalog');
    assert.equal(rows[0].recent_player_count,0);
    assert.equal(rows[0].score,0);
  });

  await check('played and already-rated games are excluded',async()=>{
    await game(1,'Played');
    await game(2,'Already Rated');
    await game(3,'Unplayed');
    await play(1,1);
    await rate(1,2,5);
    assert.deepEqual((await recommendations()).map(r=>r.game_id),[3]);
  });

  await check('different genre histories produce different personalized results without platform information',async()=>{
    const features = {developers:[],publishers:[]};
    await game(1,'RPG History',{...features,genres:[1]});
    await game(2,'Racing History',{...features,genres:[2]});
    await game(3,'RPG Recommendation',{...features,genres:[1]});
    await game(4,'Racing Recommendation',{...features,genres:[2]});
    await play(1,1);
    await play(2,2);
    const first = await recommendations(1);
    const second = await recommendations(2);
    assert.equal(first[0].game_id,3);
    assert.equal(second[0].game_id,4);
    assert.equal(first[0].source,'preferences');
    assert.equal(first[0].matched_genres,'RPG');
    assert.equal(first[0].similar_player_score,0);
    close(first[0].score,1);
  });

  await check('contributor proportions work with one played game and keep developer/publisher roles separate',async()=>{
    await game(1,'History',{genres:[],developers:[1],publishers:[5]});
    await game(2,'Same Developer',{genres:[],developers:[1],publishers:[6]});
    await game(3,'Same Publisher',{genres:[],developers:[2],publishers:[5]});
    await game(4,'Different Contributors',{genres:[],developers:[3],publishers:[6]});
    await play(1,1);
    const rows = await recommendations();
    assert.deepEqual(rows.slice(0,2).map(r=>r.game_id),[2,3]);
    assert.equal(rows[0].matched_contributors,'Studio A');
    assert.equal(rows[1].matched_contributors,'Publisher X');
    assert.equal(rows[2].source,'catalog');
  });

  await check('multiple tags divide one played game vote instead of inflating its influence',async()=>{
    const features = {developers:[],publishers:[]};
    await game(1,'Two Tags',{...features,genres:[1,2]});
    await game(2,'One Tag',{...features,genres:[3]});
    await game(3,'RPG Candidate',{...features,genres:[1]});
    await game(4,'Puzzle Candidate',{...features,genres:[3]});
    await play(1,1);
    await play(2,1);
    const rows = await recommendations();
    assert.equal(rows[0].game_id,4);
    close(rows.find(r=>r.game_id===3).preference_score,0.5);
    close(rows[0].preference_score,1);
  });

  await check('ratings affect preferences and disliked games do not create positive genre matches',async()=>{
    const features = {developers:[],publishers:[]};
    await game(1,'Liked History',{...features,genres:[1]});
    await game(2,'Disliked History',{...features,genres:[2]});
    await game(3,'Liked Genre',{...features,genres:[1]});
    await game(4,'Disliked Genre',{...features,genres:[2]});
    await play(1,1);
    await play(2,1);
    await rate(1,1,5);
    await rate(1,2,1);
    const rows = await recommendations();
    assert.equal(rows[0].game_id,3);
    assert.equal(rows.find(r=>r.game_id===4).preference_score,0);
    assert.equal(rows.find(r=>r.game_id===4).matched_genres,null);
  });

  await check('repeated history sessions are capped per game before computing preferences',async()=>{
    const features = {developers:[],publishers:[]};
    await game(1,'RPG History',{...features,genres:[1]});
    await game(2,'Racing History',{...features,genres:[2]});
    await game(3,'RPG Candidate',{...features,genres:[1]});
    await game(4,'Racing Candidate',{...features,genres:[2]});
    await play(1,1,15,1);
    await play(1,1,15,20);
    await play(2,1,20,1);
    let rows = await recommendations();
    close(rows.find(r=>r.game_id===3).preference_score,1);
    close(rows.find(r=>r.game_id===4).preference_score,1);
    await play(1,1,200,50);
    rows = await recommendations();
    close(rows.find(r=>r.game_id===3).preference_score,1);
    close(rows.find(r=>r.game_id===4).preference_score,1);
  });

  await check('similar users contribute even without a follow relationship or matching metadata',async()=>{
    await game(1,'Shared History',{genres:[1],developers:[1],publishers:[5]});
    await game(2,'Peer Suggestion',{genres:[2],developers:[2],publishers:[6]});
    await play(1,1);
    await play(1,2);
    await play(2,2);
    await rate(2,2,5);
    const rows = await recommendations();
    assert.equal(rows[0].game_id,2);
    assert.equal(rows[0].source,'similar_players');
    assert.equal(rows[0].similar_player_count,1);
    assert.equal(rows[0].followed_player_count,0);
    assert.equal(rows[0].preference_score,0);
    close(rows[0].score,1);
  });

  await check('a hybrid match combines both normalized signals equally',async()=>{
    const noContributors = {developers:[],publishers:[]};
    await game(1,'Shared History',{...noContributors,genres:[1]});
    await game(2,'Both Signals',{...noContributors,genres:[1]});
    await game(3,'Taste Only',{...noContributors,genres:[1]});
    await game(4,'Peer Only',{...noContributors,genres:[2]});
    await play(1,1);
    await play(1,2);
    await play(2,2);
    await play(4,2);
    const rows = await recommendations();
    assert.equal(rows[0].game_id,2);
    assert.equal(rows[0].source,'hybrid');
    close(rows[0].score,1);
    close(rows.find(r=>r.game_id===3).score,0.5);
    close(rows.find(r=>r.game_id===4).score,0.5);
  });

  await check('followed similar users receive a boost and unrelated followed users do not create similarity',async()=>{
    await game(1,'Shared',{genres:[],developers:[],publishers:[]});
    await game(2,'A Unfollowed Suggestion',{genres:[],developers:[],publishers:[]});
    await game(3,'Z Followed Suggestion',{genres:[],developers:[],publishers:[]});
    await game(4,'Unrelated Followed Suggestion',{genres:[],developers:[],publishers:[]});
    await play(1,1);
    await play(1,2);
    await play(1,3);
    await play(2,2);
    await play(3,3);
    await play(4,4);
    await follow(1,3);
    await follow(1,4);
    const rows = await recommendations();
    assert.equal(rows[0].game_id,3);
    assert.equal(rows[0].followed_player_count,1);
    assert.ok(rows[0].similar_player_score>rows.find(r=>r.game_id===2).similar_player_score);
    assert.equal(rows.find(r=>r.game_id===4).source,'popular');
    assert.equal(rows.find(r=>r.game_id===4).similar_player_count,0);
  });

  await check('Jaccard similarity favors a closer player over one with a larger unrelated history',async()=>{
    const features = {genres:[],developers:[],publishers:[]};
    for (let id=1;id<=8;id++) await game(id,'Game '+id,features);
    await play(1,1);
    await play(1,2);
    await play(1,3);
    await play(2,2);
    for (let id=3;id<=8;id++) await play(id,3);
    const rows = await recommendations();
    assert.equal(rows[0].game_id,2);
    assert.ok(rows[0].similar_player_score>rows.find(r=>r.game_id===3).similar_player_score);
  });

  await check('a low neighbor rating is not counted as an endorsement',async()=>{
    const features = {genres:[],developers:[],publishers:[]};
    await game(1,'Shared',features);
    await game(2,'Disliked By Peer',features);
    await game(3,'Liked By Peer',features);
    await play(1,1);
    await play(1,2);
    await play(2,2,20);
    await play(3,2,1);
    await rate(2,2,1);
    await rate(2,3,5);
    const rows = await recommendations();
    assert.equal(rows[0].game_id,3);
    assert.equal(rows.find(r=>r.game_id===2).similar_player_score,0);
    assert.equal(rows.find(r=>r.game_id===2).source,'popular');
  });

  await check('duplicate platform availability cannot inflate recommendations or explanations',async()=>{
    await own(1,1);
    await own(1,3);
    await game(1,'History');
    await game(2,'Single Platform');
    await game(3,'Multiple Platforms',{platforms:[1,2,3]});
    await play(1,1);
    const rows = await recommendations();
    assert.equal(rows.length,2);
    close(rows[0].preference_score,rows[1].preference_score);
    assert.equal(rows.find(r=>r.game_id===3).platforms,'PC, Switch');
    assert.ok(rows.every(r=>r.matched_contributors==='Publisher X, Studio A'));
  });

  await check('future and unfinished plays do not create preference or similarity signals',async()=>{
    await game(1,'Future History');
    await game(2,'Candidate');
    await db.exec(`INSERT INTO "Plays" VALUES
      (1,1,CURRENT_TIMESTAMP-INTERVAL '1 hour',CURRENT_TIMESTAMP+INTERVAL '1 hour'),
      (1,2,CURRENT_TIMESTAMP-INTERVAL '2 hours',NULL);`);
    const rows = await recommendations();
    assert.deepEqual(rows.map(r=>r.game_id),[2]);
    assert.equal(rows[0].source,'catalog');
    assert.equal(rows[0].preference_score,0);
    assert.equal(rows[0].similar_player_score,0);
  });

  await check('popular fallbacks use recent playtime only and clip sessions at the 90-day cutoff',async()=>{
    await game(1,'Old Activity');
    await game(2,'Crosses Cutoff');
    await game(3,'Recent Activity');
    await play(1,2,200,90*24+1);
    await play(2,3,2,90*24-0.5);
    await play(3,4,1);
    const rows = await recommendations();
    assert.deepEqual(rows.map(r=>r.game_id),[3,2,1]);
    assert.equal(rows[1].capped_recent_seconds,1800);
    assert.equal(rows[2].source,'catalog');
  });

  await check('results are limited to ten with stable ordering and no played titles',async()=>{
    for (let id=1;id<=15;id++) await game(id,'Game '+String(id).padStart(2,'0'));
    await play(1,1);
    assert.deepEqual((await recommendations()).map(r=>r.game_id),Array.from({length:10},(_,i)=>i+2));
  });

  if (process.argv.includes('--scale')) {
    await db.exec('BEGIN');
    try {
      await db.exec(`INSERT INTO "User" SELECT n FROM generate_series(1,1000) n;
        INSERT INTO "Platform" SELECT n,'Platform '||n FROM generate_series(1,40) n;
        INSERT INTO "Genre" SELECT n,'Genre '||n FROM generate_series(1,50) n;
        INSERT INTO "Contributor" SELECT n,'Contributor '||n FROM generate_series(1,1000) n;
        INSERT INTO "Game" SELECT n,'Game '||n FROM generate_series(1,1000) n;
        INSERT INTO "OnPlatform" SELECT g,p,DATE '2020-01-01'
          FROM generate_series(1,1000) g CROSS JOIN generate_series(1,40) p;
        INSERT INTO "GenreClassification" SELECT g,((g+n)%50)+1
          FROM generate_series(1,1000) g CROSS JOIN generate_series(1,40) n;
        INSERT INTO "Developed" SELECT g,((g+n)%1000)+1
          FROM generate_series(1,1000) g CROSS JOIN generate_series(1,40) n;
        INSERT INTO "Published" SELECT g,((g+n+50)%1000)+1
          FROM generate_series(1,1000) g CROSS JOIN generate_series(1,40) n;
        INSERT INTO "Plays" SELECT ((u+n*7)%1000)+1,u,
          CURRENT_TIMESTAMP-INTERVAL '2 hours',CURRENT_TIMESTAMP-INTERVAL '1 hour'
          FROM generate_series(1,1000) u CROSS JOIN generate_series(1,40) n;
        INSERT INTO "Rating" SELECT uid,game_id,4 FROM "Plays";
        INSERT INTO "PlatformsOwned" VALUES (1,1),(1,2);
        INSERT INTO "Following" SELECT 1,n FROM generate_series(2,21) n;
        ANALYZE;`);
      const started = Date.now();
      const rows = await recommendations();
      assert.equal(rows.length,10);
      assert.ok(rows.every(r=>r.platform_filtered && r.source==='hybrid'));
      console.log(`PASS: synthetic workload with 1,000 users/games, 40,000 plays/ratings, and 160,000 catalog links (${Date.now()-started} ms).`);
      passed++;
    } finally {
      await db.exec('ROLLBACK');
    }
  }

  console.log(`PASS: ${passed} isolated PostgreSQL recommendation scenarios. Starbug was not changed.`);
} catch (error) {
  console.error('FAIL:',error.code ?? error.name,error.message);
  process.exitCode = 1;
} finally {
  await db.close();
}
