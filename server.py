import asyncio
import html
import os
import traceback

import websockets
import ffmpeg
import json
import youtube_dl
import uuid

from pylast import WSError
from tinydb import TinyDB, Query
import re
from random_word import RandomWords
from Levenshtein import distance as levenshtein_distance
import time
import sqlite3
import pylast
import random
import math
from dotenv import load_dotenv

load_dotenv()

not_quite_infinite = 9999999999999999999

sqlite_con = sqlite3.connect('intro.db')
sqlite_con.row_factory = sqlite3.Row

sqlite_cur = sqlite_con.cursor()

GAMES = {}
rrr = RandomWords()

lastfm_network = pylast.LastFMNetwork(
    api_key=os.getenv('LAST_API_KEY'),
    api_secret=os.getenv('LAST_API_SECRET'),
)


async def handle(websocket, path):
    if path != '/version/1.1':
        await websocket.send(json.dumps({'action': 'showerror',
                                         'msg': 'The client and server version are not compatible! Please reload your page'}))
        await asyncio.sleep(10)
        await websocket.close()
        return
    websocket.name = ' '.join(rrr.get_random_words(limit=2, maxLength=10))
    websocket.uuid = str(uuid.uuid4())
    websocket.game = None
    websocket.guess = None
    websocket.points = 0

    try:
        await websocket.send(json.dumps(
            {'action': 'welcome', 'uuid': websocket.uuid, 'name': websocket.name,
             'ip': websocket.request_headers.get('X-Forwarded-For') or websocket.remote_address[0]})
        )
        async for message in websocket:
            await msg(message, websocket)
    except Exception as e:
        print(e)
        traceback.print_exc()
        pass
    finally:
        if websocket.game:
            g = websocket.game
            print("Leaving " + g['words'])
            g['players'].remove(websocket)
            if len(g['players']) == 0:
                print("Deleting " + g['words'])
                del GAMES[g['words']]
                pass
            if g['host'] == websocket:
                await broadcast_to_game(g, {'action': 'showerror', 'msg': 'The host left the game :/'})
                pass  # TODO: New host
            await broadcast_to_game(g, {'action': 'player_left',
                                        'uuid': websocket.uuid,
                                        'players': {u.uuid: u.name for u in g['players']}})
            if g['state'] == 'playing':
                all_players_guessed = True
                for p in websocket.game['players']:
                    if not p.guess or "has_sent_guess" in p.guess:
                        all_players_guessed = False
                        break
                if all_players_guessed:  # next
                    await game_show_result(websocket.game)

        pass


async def broadcast_to_game(g, message):
    if g['players']:
        await asyncio.wait([asyncio.create_task(user.send(json.dumps(message))) for user in g['players']])


async def finish_game(g):
    # In case no new questions are found we just do nothing - for now
    pass


# check the distance
# also penalize for different lengths
def calculate_string_distance(orig, reply):
    d = levenshtein_distance(re.sub(r'[^a-z0-9]+', '', orig.lower()), re.sub(r'[^a-z0-9]+', '', reply.lower()))
    return (1 - min(1, d / len(reply))) if len(reply) else -5


def fetch_last_fm(data, lastfm_track, uuid):
    print("FETCHING ", lastfm_track)
    try:
        data['error'] = False
        data['lastfm_url'] = lastfm_track.get_url()
        a = lastfm_track.get_album()
        data['lastfm_album'] = a.get_name() if a else None
        try:
            data['lastfm_cover'] = lastfm_track.get_cover_image()
        except IndexError:
            data['lastfm_cover'] = None
            pass
        data['lastfm_tags'] = [{'song': uuid, 'tag': x.item.name, 'weight': x.weight} for x in
                               lastfm_track.get_top_tags(10)]
        print(data)
    except WSError as e:
        data['error'] = e.details
        print("Error", e)


# distribute points from distances
def group_points(dists):
    points = {}
    last_dist = not_quite_infinite
    last_points = len(dists)
    real_points = last_points
    for p_uuid in dists:
        if last_dist > dists[p_uuid]:
            last_dist = dists[p_uuid]
            last_points = real_points
        points[p_uuid] = last_points
        real_points = real_points - 1
    return points


def show_help(orig, percentage):
    if percentage <= 0:
        return ''
    rep = re.sub(r'\S', '_', orig)
    rep = list(rep)
    positions = list(filter(lambda p: orig[p] != ' ', range(0, len(rep))))
    random.shuffle(positions)
    n = math.floor(len(orig) * min(max(percentage, 0), 100) / 100)
    for r in positions[:n]:
        rep[r] = orig[r]

    return ''.join(rep)\


async def game_show_result(g):
    sqlite_cur.execute('SELECT * FROM songs WHERE uuid = ?', (g['current_song'],))
    current_question = sqlite_cur.fetchone()
    exp_title = re.sub(r'[^a-z0-9]+', '', current_question['title'].lower())
    exp_artist = re.sub(r'[^a-z0-9]+', '', current_question['artist'].lower())

    g['state'] = 'results'
    results = []
    artist_dists = {}
    title_dists = {}
    for p in g['players']:
        guessed_title = p.guess['title'] if p.guess else ''
        guessed_artist = p.guess['artist'] if p.guess else ''

        a_dist = calculate_string_distance(exp_artist, guessed_artist)
        t_dist = calculate_string_distance(exp_title, guessed_title)

        guess = {
            'uuid': p.uuid,
            'artist': guessed_artist if guessed_artist else '?',
            'title': guessed_title if guessed_artist else '?',
            'artist_distance': a_dist,
            'title_distance': t_dist,
        }
        results.append(guess)
        artist_dists[p.uuid] = a_dist
        title_dists[p.uuid] = t_dist
    # sort the distances
    artist_dists = {k: v for k, v in sorted(artist_dists.items(), key=lambda item: item[1], reverse=True)}
    title_dists = {k: v for k, v in sorted(title_dists.items(), key=lambda item: item[1], reverse=True)}

    # award points for artist and title
    artist_points = group_points(artist_dists)
    title_points = group_points(title_dists)

    # finally award the points to the players
    for p in g['players']:
        if p.uuid in artist_points:
            p.points += artist_points[p.uuid]
        if p.uuid in title_points:
            p.points += title_points[p.uuid]

    await broadcast_to_game(g, {
        'action': 'show_stage',
        'stage': 'game_results',
        'yt_id': current_question['yt_id'],
        'cover_image': current_question['lastfm_cover'],
        'song_uuid': current_question['uuid'],
        'long_file': 'songs/game/' + current_question['yt_id'] + ".mp3",
        'artist': current_question['artist'],
        'title': current_question['title'],
        'artist_points': artist_points,
        'title_points': title_points,
        'guesses': results,
        'points': {u.uuid: u.points for u in g['players']},
        'words': g['words']})
    pass


async def send_join_game(websocket, g, host=False):
    await websocket.send(json.dumps(
        {'action': 'show_stage',
         'stage': 'join_game',
         'state': g['state'],
         'path': 'songs/game/' + g['current_song'] + '.mp3' if g['current_song'] else None,
         'result_yt_id': 'dQw4w9WgXcQ',
         'words': g['words'],
         'host': host,
         'points': {u.uuid: u.points for u in g['players']},
         'players': {u.uuid: u.name for u in g['players']},
         }))


async def msg(str_msg, websocket):
    data = json.loads(str_msg)
    print(f"< {data}")
    if data['command'] == 'start_game':
        if 'name' in data and len(data['name']):
            websocket.name = html.escape(data['name'])
        words = ' '.join(rrr.get_random_words(limit=5, maxLength=10))
        game = {
            'host': websocket,
            'words': words,
            'players': [websocket],
            'previous': [],
            'current': None,
            'last_seen': None,
            'state': 'WAITING',
            'current_song': None,
            'help_percentage': int(data['help_percentage']) if 'help_percentage' in data else 0,
            'song_tags': data['song_tags'],
        }
        GAMES[words] = game
        websocket.game = game
        print(f"new {game}")
        await send_join_game(websocket, game, True)
    elif data['command'] == 'join_game':
        if 'name' in data and len(data['name']):
            websocket.name = data['name']
        if data['words'] not in GAMES:
            await websocket.send(json.dumps({'action': 'showerror', 'msg': 'No room found'}))
            return
        # Join game
        g = GAMES[data['words']]
        g['players'].append(websocket)
        websocket.game = g
        await broadcast_to_game(g, {'action': 'player_joined', 'name': websocket.name, 'uuid': websocket.uuid,
                                    'words': g['words'],
                                    'points': {u.uuid: u.points for u in g['players']},
                                    'players': {u.uuid: u.name for u in g['players']},
                                    })
        await send_join_game(websocket, g, False)
    elif data['command'] == 'game_next_req':
        if not websocket.game:
            await websocket.send(json.dumps({'action': 'showerror', 'msg': 'No room found'}))
            return
        await broadcast_to_game(websocket.game,
                                {'action': 'player_request_continue',
                                 'name': websocket.name,
                                 'uuid': websocket.uuid,
                                 'words': websocket.game['words']})
    elif data['command'] == 'game_set_guess':
        if not websocket.game:
            await websocket.send(json.dumps({'action': 'showerror', 'msg': 'No room found'}))
            return
        websocket.guess = data['guess']
        if "announce" in websocket.guess:
            await broadcast_to_game(websocket.game, {
                'action': 'player_guessed',
                'name': websocket.name,
                'uuid': websocket.uuid,
                'words': websocket.game['words']})

        all_players_guessed = True
        for p in websocket.game['players']:
            if not p.guess or "has_sent_guess" not in p.guess:
                all_players_guessed = False
                break
        if all_players_guessed:  # next
            await game_show_result(websocket.game)
    elif data['command'] == 'game_force_vote':
        if not websocket.game:
            await websocket.send(json.dumps({'action': 'showerror', 'msg': 'No room found'}))
            return
        g = websocket.game
        if g['host'] != websocket:
            await websocket.send(json.dumps({'action': 'showerror', 'msg': 'Not the host'}))
            return
        if g['state'] == 'playing':
            await broadcast_to_game(g, {
                'action': 'game_progress_bar',
                'value': '100',
                'time': data['time'],
                'words': g['words']})
            if data['time'] == 0:
                await game_show_result(g)
    elif data['command'] == 'game_force_next_round':
        if not websocket.game:
            await websocket.send(json.dumps({'action': 'showerror', 'msg': 'No room found'}))
            return
        g = websocket.game
        if g['host'] != websocket:
            await websocket.send(json.dumps({'action': 'showerror', 'msg': 'Not the host'}))
            return
        if g['state'] == 'results':
            await broadcast_to_game(g, {
                'action': 'results_progress_bar',
                'value': '100',
                'time': data['time'],
                'words': g['words']})
    elif data['command'] == 'game_next':
        # something
        if not websocket.game:
            await websocket.send(json.dumps({'action': 'showerror', 'msg': 'No room found'}))
            return
        g = websocket.game
        if g['host'] != websocket:
            await websocket.send(json.dumps({'action': 'showerror', 'msg': 'Not the host'}))
            return
        prev_str = '?' + ',?' * (len(g['previous']) - 1) if g['previous'] else ''
        if len(g['song_tags']) == 0:
            sqlite_cur.execute(f'SELECT songs.* FROM songs WHERE yt_id NOT IN ({prev_str}) ORDER BY RANDOM() LIMIT 1',
                               g['previous'])
        else:
            tag_str = '?' + ',?' * (len(g['song_tags']) - 1)
            params = g['song_tags'] + g['previous']
            sqlite_cur.execute(
                f'SELECT songs.* FROM songs JOIN song_tags ON song_tags.song_uuid = songs.uuid AND song_tags.tag IN ({tag_str}) WHERE yt_id NOT IN ({prev_str}) ORDER BY RANDOM() LIMIT 1',
                params)

        question = sqlite_cur.fetchone()
        if not question:  # no new found
            await finish_game(g)
            return
        question_uuid = question['uuid']
        g['current_song'] = question_uuid
        g['state'] = 'playing'
        g['previous'].append(question['yt_id'])
        for p in websocket.game['players']:
            p.guess = None
        await broadcast_to_game(g, {'action': 'game_next',
                                    'path': f'songs/game/{question_uuid}.mp3',
                                    'help_artist': show_help(question['artist'], g['help_percentage']),
                                    'help_title': show_help(question['title'], g['help_percentage']),
                                    'result_yt_id': 'dQw4w9WgXcQ',
                                    'words': g['words']})
    elif data['command'] == 'admin_list_songs':
        if data['password'] == os.getenv('ADMIN_PWD'):
            sqlite_cur.execute('''SELECT songs.*,song_tags.*, 
            count(srbad.type) as count_bad, count(srlike.type) as count_like, count(srwrong.type) as count_wrong
             FROM songs 
            LEFT JOIN song_tags ON songs.uuid = song_tags.song_uuid
            LEFT JOIN song_reports srbad on songs.uuid = srbad.song_uuid AND srbad.type = 'bad'
            LEFT JOIN song_reports srlike on songs.uuid = srlike.song_uuid AND srlike.type = 'like'
            LEFT JOIN song_reports srwrong on songs.uuid = srwrong.song_uuid AND srwrong.type = 'wrong'
            GROUP BY songs.uuid, song_tags.tag
            ''')
            songs = [dict(row) for row in sqlite_cur.fetchall()]
            await websocket.send(
                json.dumps(
                    {'action': 'show_stage', 'stage': 'admin_show_songs', 'songs': songs}))
        else:
            print("invalid password", os.getenv('ADMIN_PWD'))
    elif data['command'] == 'report_song':
        song_uuid = re.sub(r'[^a-zA-Z0-9\-]+', '', data['uuid'])
        if not data['votetype'] in ['good', 'bad', 'wrong']:
            raise Exception('Unknown vote type')
        sqlite_cur.execute('SELECT 1 FROM songs WHERE uuid=?', (song_uuid,))
        if not sqlite_cur.fetchone():
            raise Exception('Song not found')
        client_ip = websocket.request_headers.get('X-Forwarded-For') or websocket.remote_address[0]
        sqlite_cur.execute('SELECT 1 FROM song_reports WHERE song_uuid=? AND client_ip =?', (song_uuid, client_ip))
        if sqlite_cur.fetchone():  # skip duplicates
            return
        sqlite_con.execute(
            "insert into song_reports (song_uuid, time_created, client_ip, type) "
            + " values (?,?,?,?)", [song_uuid, time.time(), client_ip, data['votetype']])
        sqlite_con.commit()
    elif data['command'] == 'fetch_tags':
        sqlite_cur.execute('''SELECT song_tags.tag, count(*) songs
            FROM song_tags
            LEFT JOIN songs ON songs.uuid = song_tags.song_uuid
            -- WHERE song_tags.weight > 5
            GROUP BY song_tags.tag
            HAVING count(*) > 5
            ORDER BY count(*) DESC''')
        tags = [{'tag': row['tag'], 'songs': row['songs']} for row in sqlite_cur.fetchall()]
        tags = sorted(tags, key=lambda item: item['songs'], reverse=True)
        await websocket.send(
            json.dumps(
                {'action': 'reply_fetch_tags', 'tags': tags}))
    elif data['command'] == 'init_download':
        yt = find_yt_urls(data['id'])
        await websocket.send(json.dumps({'action': 'show_progress', 'msg': 'Downloading song information'}))
        if not yt:
            await websocket.send(json.dumps({'action': 'showerror', 'msg': 'Failed to find song'}))
            return
        await websocket.send(json.dumps({'action': 'show_progress', 'msg': 'Downloading song...'}))
        song_uuid = str(uuid.uuid4())
        songpath = f'songs/tmp/{song_uuid}.mp3'
        ffmpeg.input(yt['url'], t=20).output('public/' + songpath, codec='libmp3lame').run()
        await websocket.send(
            json.dumps({'action': 'show_stage',
                        'stage': 'song_get_data',
                        'title': yt['title'],
                        'file': songpath,
                        'yt_id': data['id'],
                        'uuid': song_uuid}))
    elif data['command'] == 'init_fetch':
        lastfm_track = lastfm_network.get_track(data['artist'].strip(), data['title'].strip())
        data = {'action': 'show_stage',
                'stage': 'song_prepare',
                'error': False,
                'lastfm_url': None,
                'lastfm_album': None,
                'lastfm_cover': None,
                'lastfm_tags': None,
                }
        fetch_last_fm(data, lastfm_track, 'loading')
        await websocket.send(json.dumps(data))
    elif data['command'] == 'init_add':
        print(data)
        song_uuid = re.sub(r'[^a-zA-Z0-9\-]+', '', data['uuid'])
        sqlite_cur.execute('SELECT 1 FROM songs WHERE uuid=?', (song_uuid,))
        if sqlite_cur.fetchone():
            raise Exception('Already existing')
        song_tmp_path = f'public/songs/tmp/{song_uuid}.mp3'
        song_final_path = f'public/songs/game/{song_uuid}.mp3'

        time_start = max(0, min(20000, int(data['time_start'])))
        time_end = max(0, min(20000, int(data['time_end'])))

        duration = abs(time_end - time_start)
        await websocket.send(json.dumps({'action': 'show_progress', 'msg': 'Working on intro'}))

        print(f"Converting snippet from {time_start} to {time_end} for {duration}ms")
        ffmpeg.input(song_tmp_path, t=f'{duration}ms', ss=f'{time_start}ms') \
            .output(song_final_path, codec='libmp3lame').run()
        os.remove(song_tmp_path)

        lastfm_track = lastfm_network.get_track(data['artist'].strip(), data['title'].strip())
        lastfm_data = {'error': False,
                       'lastfm_url': None,
                       'lastfm_album': None,
                       'lastfm_cover': None,
                       'lastfm_tags': []}
        fetch_last_fm(lastfm_data, lastfm_track, song_uuid)

        # also download a longer version
        yt = find_yt_urls(data['yt_id'])
        if not yt:
            await websocket.send(json.dumps({'action': 'showerror', 'msg': 'Failed to download song'}))
            return
        await websocket.send(json.dumps({'action': 'show_progress', 'msg': 'Downloading song (again)...'}))

        song_long_path = 'public/songs/game/' + data['yt_id'] + '.mp3'
        if not os.path.isfile(song_long_path):
            print(f"Downloading long 60s")
            ffmpeg.input(yt['url'], t=60, ss=f'{time_start}ms').output(song_long_path, codec='libmp3lame').run()
        song_data = {'type': 'song',
                     'yt_id': data['yt_id'],
                     'uuid': song_uuid,
                     'artist': data['artist'].strip(),
                     'title': data['title'].strip(),
                     'time_created': time.time(),
                     'duration': duration,
                     'time_start': time_start,
                     'client_ip': websocket.request_headers.get('X-Forwarded-For') or websocket.remote_address[0],
                     'lastfm_url': lastfm_data['lastfm_url'],
                     'lastfm_album': lastfm_data['lastfm_album'],
                     'lastfm_cover': lastfm_data['lastfm_cover'],
                     }
        sqlite_con.execute(
            "insert into songs (yt_id, uuid, artist, title, time_created, duration, time_start, client_ip, lastfm_url, lastfm_album, lastfm_cover) "
            + " values (:yt_id, :uuid, :artist, :title, :time_created, :duration, :time_start, :client_ip, :lastfm_url, :lastfm_album, :lastfm_cover)",
            song_data)
        sqlite_con.executemany(
            "insert into song_tags (song_uuid, tag, weight) "
            + " values (:song, :tag, :weight)",
            lastfm_data['lastfm_tags'])
        sqlite_con.commit()

        await websocket.send(json.dumps({'action': 'show_stage', 'stage': 'song_init'}))

    else:
        greeting = f"Hello {data}!"

        await websocket.send(json.dumps({'msg': greeting}))
        print(f"> {greeting}")


def find_yt_urls(youtube_id):
    ydl = youtube_dl.YoutubeDL()
    try:
        with ydl:
            res = ydl.extract_info('https://www.youtube.com/watch?v=' + youtube_id, download=False)
            if 'entries' in res:
                raise Exception("Playlist not supported")
            for f in res['formats']:
                if f['format_id'] == "140":
                    return {
                        'url': f['url'],
                        'title': res['title'],
                        'id': res['id'],
                    }
    except:
        return False


def migrate():
    QQ = Query()
    db = TinyDB('db.json')
    songs = db.search(QQ.type == 'song')
    gamedir = 'public/songs/game/'
    for s in songs:
        # Migration 1: Download 60sec "result" track
        path = gamedir + s['yt_id'] + '.mp3'
        if not os.path.isfile(path):
            print("Migrating by downloading long file to " + path)
            starttime = s['time_start'] if 'time_start' in s else 0
            yt = find_yt_urls(s['yt_id'])
            if yt:
                song_long_path = 'public/songs/game/' + s['yt_id'] + '.mp3'
                ffmpeg.input(yt['url'], t=60, ss=f'{starttime}ms').output(song_long_path, codec='libmp3lame').run()

        # migrate into
        if s['type'] == 'song':
            s['title'] = s['title'].strip()
            s['artist'] = s['artist'].strip()

            sqlite_cur.execute('SELECT 1 FROM songs WHERE uuid=?', (s['uuid'],))
            if not sqlite_cur.fetchone():
                print("Migrating to db")
                print(s)
                if "lastfm_url" not in s:
                    lastfm_track = lastfm_network.get_track(s['artist'], s['title'])
                    try:
                        print(lastfm_track)
                        s['lastfm_url'] = lastfm_track.get_url()
                        a = lastfm_track.get_album()
                        s['lastfm_album'] = a.get_name() if a else None
                        try:
                            s['lastfm_cover'] = lastfm_track.get_cover_image()
                        except IndexError:
                            s['lastfm_cover'] = None
                            pass
                        s['lastfm_tags'] = [{'song': s['uuid'], 'tag': x.item.name, 'weight': x.weight} for x in
                                            lastfm_track.get_top_tags(10)]
                        time.sleep(1)
                    except WSError as e:
                        if e.details == 'Track not found':
                            s['lastfm_url'] = None
                            s['lastfm_album'] = None
                            s['lastfm_cover'] = None
                            s['lastfm_tags'] = []
                        else:  # some other error
                            raise e
                # Migrate: Insert into DB
                if 'time_created' not in s:
                    s['time_created'] = 0
                if 'time_start' not in s:
                    s['time_start'] = 0
                if 'client_ip' not in s:
                    s['client_ip'] = '127.0.0.1'
                print(s)
                sqlite_con.execute(
                    "insert into songs (yt_id, uuid, artist, title, time_created, duration, time_start, client_ip, lastfm_url, lastfm_album, lastfm_cover) "
                    + " values (:yt_id, :uuid, :artist, :title, :time_created, :time, :time_start, :client_ip, :lastfm_url, :lastfm_album, :lastfm_cover)",
                    s)
                sqlite_con.executemany(
                    "insert into song_tags (song_uuid, tag, weight) "
                    + " values (:song, :tag, :weight)",
                    s['lastfm_tags'])
                sqlite_con.commit()


sqlite_con.execute('''CREATE TABLE IF NOT EXISTS songs
               (yt_id text, uuid text, artist text, title text, time_created real, duration real,
                time_start real, client_ip text, lastfm_url text, lastfm_album text, lastfm_cover text)''')
sqlite_con.execute('''CREATE TABLE IF NOT EXISTS song_tags
               (song_uuid text, tag text, weight real)''')
sqlite_con.execute('''CREATE TABLE IF NOT EXISTS song_reports
               (song_uuid text, time_created text, client_ip text, type text)''')

migrate()
print("Starting...")
start_server = websockets.serve(handle, "0.0.0.0", 8765)

asyncio.get_event_loop().run_until_complete(start_server)
asyncio.get_event_loop().run_forever()

sqlite_con.close()
