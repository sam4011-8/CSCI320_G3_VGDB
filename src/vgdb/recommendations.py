"""Explicit SQL for explainable content and similar-player recommendations."""

RECOMMENDATION_LIMIT = 10
SIMILAR_PLAYER_LIMIT = 20
FOLLOWED_PLAYER_BOOST = 1.25


def recommendation_query(uid, cap_seconds, popularity_days):
    """Return parameterized SQL; scores are relative rankings, not probabilities."""
    return RECOMMENDATION_SQL, {
        'uid': uid, 'cap_seconds': cap_seconds, 'days': popularity_days,
        'neighbor_limit': SIMILAR_PLAYER_LIMIT, 'limit': RECOMMENDATION_LIMIT,
        'follow_boost': FOLLOWED_PLAYER_BOOST,
    }


RECOMMENDATION_SQL = '''
WITH clock AS (
    SELECT CURRENT_TIMESTAMP AS now_at
), viewer AS (
    SELECT uid FROM "User" WHERE uid=%(uid)s
), seen_games AS (
    SELECT game_id FROM "Plays" WHERE uid=%(uid)s
    UNION
    SELECT game_id FROM "Rating" WHERE uid=%(uid)s
), owned_platforms AS (
    SELECT platform_id FROM "PlatformsOwned" WHERE uid=%(uid)s
), play_totals AS (
    -- Aggregate sessions before joining any multi-valued catalog relationships.
    SELECT p.uid, p.game_id,
           LEAST(SUM(EXTRACT(EPOCH FROM (p.end_time-p.start_time))),%(cap_seconds)s) AS capped_seconds,
           LEAST(COALESCE(SUM(EXTRACT(EPOCH FROM
               (p.end_time-GREATEST(p.start_time,w.now_at-(%(days)s * INTERVAL '1 day')))))
               FILTER (WHERE p.end_time>w.now_at-(%(days)s * INTERVAL '1 day')),0),
               %(cap_seconds)s) AS recent_seconds
    FROM "Plays" p CROSS JOIN clock w
    WHERE p.end_time<=w.now_at AND p.start_time<p.end_time
    GROUP BY p.uid, p.game_id
), history AS (
    -- Explicit low ratings do not contribute positive taste or neighbor votes.
    -- An unrated game uses a neutral 3/5 rating weight.
    SELECT t.uid, t.game_id, t.recent_seconds,
           CASE WHEN r.rating<=2 THEN 0::NUMERIC
                ELSE (COALESCE(r.rating,3)/5.0) *
                     (0.5+0.5*t.capped_seconds/%(cap_seconds)s) END AS interest_weight
    FROM play_totals t LEFT JOIN "Rating" r ON r.uid=t.uid AND r.game_id=t.game_id
), viewer_history AS (
    SELECT game_id, interest_weight FROM history WHERE uid=%(uid)s
), candidates AS (
    -- A compatible platform must already have released this game.
    SELECT g.game_id, g.game_name,
           string_agg(DISTINCT pl.platform_name, ', ' ORDER BY pl.platform_name) AS platforms,
           EXISTS (SELECT 1 FROM owned_platforms) AS platform_filtered
    FROM "Game" g JOIN "OnPlatform" op USING (game_id)
    JOIN "Platform" pl USING (platform_id) CROSS JOIN clock w CROSS JOIN viewer v
    WHERE op.release_date<=w.now_at::DATE
      AND (NOT EXISTS (SELECT 1 FROM owned_platforms) OR
           EXISTS (SELECT 1 FROM owned_platforms o WHERE o.platform_id=op.platform_id))
      AND NOT EXISTS (SELECT 1 FROM seen_games s WHERE s.game_id=g.game_id)
    GROUP BY g.game_id, g.game_name
), game_features AS (
    SELECT game_id, 'genre'::TEXT AS kind, genre_id AS feature_id FROM "GenreClassification"
    UNION ALL
    SELECT game_id, 'developer', contributor_id FROM "Developed"
    UNION ALL
    SELECT game_id, 'publisher', contributor_id FROM "Published"
), weighted_features AS (
    -- Each distinct played game divides its weight among its features of a kind.
    -- A game with many tags or contributors does not cast extra preference votes.
    SELECT f.game_id, f.kind, f.feature_id,
           h.interest_weight/COUNT(*) OVER (PARTITION BY f.game_id,f.kind) AS feature_weight
    FROM game_features f JOIN viewer_history h USING (game_id)
    WHERE h.interest_weight>0
), feature_preferences AS (
    SELECT kind, feature_id,
           SUM(feature_weight)/SUM(SUM(feature_weight)) OVER (PARTITION BY kind) AS affinity
    FROM weighted_features GROUP BY kind, feature_id
), preference_kinds AS (
    SELECT DISTINCT kind FROM feature_preferences
), content_kind_scores AS (
    SELECT f.game_id, f.kind, SUM(COALESCE(p.affinity,0))/COUNT(*) AS kind_score
    FROM game_features f JOIN candidates c USING (game_id)
    JOIN preference_kinds k USING (kind)
    LEFT JOIN feature_preferences p ON p.kind=f.kind AND p.feature_id=f.feature_id
    GROUP BY f.game_id, f.kind
), content_scores AS (
    SELECT game_id, AVG(kind_score) AS preference_raw FROM content_kind_scores GROUP BY game_id
), overlap_counts AS (
    SELECT h.uid, COUNT(*) AS shared_count
    FROM history h JOIN viewer_history v USING (game_id)
    WHERE h.uid<>%(uid)s GROUP BY h.uid
), history_counts AS (
    SELECT uid, COUNT(*) AS game_count FROM history GROUP BY uid
), neighbors AS (
    -- Jaccard overlap: shared distinct games / all distinct games of both users.
    SELECT o.uid,
           o.shared_count::NUMERIC /
               (h.game_count+(SELECT COUNT(*) FROM viewer_history)-o.shared_count) *
               CASE WHEN EXISTS (SELECT 1 FROM "Following" f
                                 WHERE f.uid=%(uid)s AND f.followed_id=o.uid)
                    THEN %(follow_boost)s::NUMERIC ELSE 1 END AS weight,
           EXISTS (SELECT 1 FROM "Following" f
                   WHERE f.uid=%(uid)s AND f.followed_id=o.uid) AS followed
    FROM overlap_counts o JOIN history_counts h USING (uid)
    ORDER BY weight DESC, o.shared_count DESC, o.uid ASC LIMIT %(neighbor_limit)s
), neighbor_scores AS (
    SELECT h.game_id, SUM(n.weight*h.interest_weight) AS neighbor_raw,
           COUNT(*) AS similar_player_count,
           COUNT(*) FILTER (WHERE n.followed) AS followed_player_count
    FROM history h JOIN neighbors n USING (uid) JOIN candidates c USING (game_id)
    WHERE h.interest_weight>0 GROUP BY h.game_id
), recent_popularity AS (
    SELECT game_id, COUNT(*) AS recent_player_count,
           SUM(recent_seconds)::BIGINT AS capped_recent_seconds
    FROM history WHERE recent_seconds>0 GROUP BY game_id
), raw_scores AS (
    SELECT c.game_id, c.game_name, c.platforms, c.platform_filtered,
           COALESCE(p.preference_raw,0) AS preference_raw,
           COALESCE(n.neighbor_raw,0) AS neighbor_raw,
           COALESCE(n.similar_player_count,0) AS similar_player_count,
           COALESCE(n.followed_player_count,0) AS followed_player_count,
           COALESCE(r.recent_player_count,0) AS recent_player_count,
           COALESCE(r.capped_recent_seconds,0)::BIGINT AS capped_recent_seconds
    FROM candidates c LEFT JOIN content_scores p USING (game_id)
    LEFT JOIN neighbor_scores n USING (game_id) LEFT JOIN recent_popularity r USING (game_id)
), scaled_scores AS (
    SELECT game_id, game_name, platforms, platform_filtered, similar_player_count,
           followed_player_count, recent_player_count, capped_recent_seconds,
           COALESCE(preference_raw/NULLIF(MAX(preference_raw) OVER (),0),0) AS preference_score,
           COALESCE(neighbor_raw/NULLIF(MAX(neighbor_raw) OVER (),0),0) AS similar_player_score
    FROM raw_scores
), scored AS (
    SELECT game_id, game_name, platforms, platform_filtered, similar_player_count,
           followed_player_count, recent_player_count, capped_recent_seconds,
           preference_score, similar_player_score,
           CASE WHEN MAX(preference_score) OVER ()>0 AND MAX(similar_player_score) OVER ()>0
                THEN (preference_score+similar_player_score)/2
                ELSE preference_score+similar_player_score END AS score
    FROM scaled_scores
), selected AS (
    SELECT game_id, game_name, platforms, platform_filtered, similar_player_count,
           followed_player_count, recent_player_count, capped_recent_seconds,
           preference_score, similar_player_score, score,
           CASE WHEN preference_score>0 AND similar_player_score>0 THEN 'hybrid'
                WHEN preference_score>0 THEN 'preferences'
                WHEN similar_player_score>0 THEN 'similar_players'
                WHEN recent_player_count>0 THEN 'popular'
                ELSE 'catalog' END AS source
    FROM scored
    ORDER BY score DESC, recent_player_count DESC, capped_recent_seconds DESC, game_name ASC, game_id ASC
    LIMIT %(limit)s
)
SELECT s.game_id, s.game_name, s.platforms, s.platform_filtered, s.source,
       s.preference_score, s.similar_player_score, s.score,
       s.similar_player_count, s.followed_player_count,
       s.recent_player_count, s.capped_recent_seconds,
       genres.names AS matched_genres, contributors.names AS matched_contributors
FROM selected s
LEFT JOIN LATERAL (
    SELECT string_agg(m.genre_name, ', ' ORDER BY m.affinity DESC,m.genre_name) AS names
    FROM (
        SELECT ge.genre_name, p.affinity
        FROM "GenreClassification" gc JOIN "Genre" ge USING (genre_id)
        JOIN feature_preferences p ON p.kind='genre' AND p.feature_id=gc.genre_id
        WHERE gc.game_id=s.game_id ORDER BY p.affinity DESC, ge.genre_name, ge.genre_id LIMIT 3
    ) m
) genres ON TRUE
LEFT JOIN LATERAL (
    SELECT string_agg(m.contributor_name, ', ' ORDER BY m.affinity DESC,m.contributor_name) AS names
    FROM (
        SELECT c.contributor_id, c.contributor_name, MAX(p.affinity) AS affinity
        FROM game_features f JOIN feature_preferences p USING (kind,feature_id)
        JOIN "Contributor" c ON c.contributor_id=f.feature_id
        WHERE f.game_id=s.game_id AND f.kind IN ('developer','publisher')
        GROUP BY c.contributor_id,c.contributor_name
        ORDER BY MAX(p.affinity) DESC,c.contributor_name,c.contributor_id LIMIT 3
    ) m
) contributors ON TRUE
ORDER BY s.score DESC, s.recent_player_count DESC, s.capped_recent_seconds DESC, s.game_name ASC, s.game_id ASC
'''
