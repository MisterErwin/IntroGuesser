import asyncio
import html
import os
import string
import traceback

import websockets
import ffmpeg
import json
import uuid

import re
# from random_word import RandomWords
from Levenshtein import distance as levenshtein_distance
import time
import sqlite3
import pylast
import random
import math
from dotenv import load_dotenv
import lxml.html as lxhtml
import requests
from serverhelper import fetch_last_fm

load_dotenv()

not_quite_infinite = 9999999999999999999

sqlite_con = sqlite3.connect('intro.db')
sqlite_con.row_factory = sqlite3.Row

sqlite_cur = sqlite_con.cursor()

GAMES = {}
# rrr = RandomWords()

lastfm_network = pylast.LastFMNetwork(
    api_key=os.getenv('LAST_API_KEY'),
    api_secret=os.getenv('LAST_API_SECRET'),
)

# Env option to disable the addition of new tracks
disable_adding = 'DISABLE_ADDING' in os.environ

async def handle(websocket, path):
    if path != '/version/1.2.2':
        await websocket.send(json.dumps({'action': 'showerror',
                                         'msg': 'The client and server version are not compatible! Please reload your page...',
                                         'version': path}))
        await asyncio.sleep(10)
        await websocket.close()
        return
    # websocket.name = ' '.join(rrr.get_random_words(limit=2, maxLength=10))
    websocket.name = 'Your name here'
    websocket.uuid = str(uuid.uuid4())
    websocket.game = None
    websocket.guess = None
    websocket.points = 0

    try:
        await websocket.send(json.dumps(
            {'action': 'welcome', 'uuid': websocket.uuid, 'name': websocket.name,
             'ip': websocket.request_headers.get('X-Forwarded-For') or websocket.remote_address[0],
             'allow_adding': not disable_adding})
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
            g['offline_points'][websocket.name] = websocket.points
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



# distribute points from distances
def group_points(dists, inverse=False, real_points=None):
    points = {}
    last_dist = -1 if inverse else not_quite_infinite
    last_points = len(dists)
    if real_points is None:
        real_points = last_points
    for p_uuid in dists:
        if (last_dist > dists[p_uuid] and not inverse) or (last_dist < dists[p_uuid] and inverse):
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
    if g['input_mode'] == 'mc':
        correct_players = {}
        for p in g['players']:
            if p.presenter: continue
            guessed_title = p.guess['title'] if p.guess else ''
            guessed_artist = p.guess['artist'] if p.guess else ''
            guess = {
                'uuid': p.uuid,
                'artist': guessed_artist if guessed_artist else '?',
                'title': guessed_title if guessed_artist else '?',
            }
            results.append(guess)
            if guessed_artist == current_question['artist'] and guessed_title == current_question['title']:
                correct_players[p.uuid] = p.guess['time']
        # sort by time
        correct_players = {k: v for k, v in sorted(correct_players.items(), key=lambda item: item[1], reverse=False)}
        print("correct_players", correct_players)
        # award points
        n_players = len(g['players'])
        if g['presentation_mode']:
            n_players = n_players-1
        title_points = group_points(correct_players, True, n_players)
        # finally award the points to the players
        for p in g['players']:
            if p.uuid in title_points:
                p.points += title_points[p.uuid]
                print(p.guess['time'], title_points[p.uuid])
        # title_points = []
        artist_points = []
    else:
        artist_dists = {}
        title_dists = {}
        for p in g['players']:
            if p.presenter: continue
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
        'points': {u.uuid: u.points for u in g['players'] if not u.presenter},
        'display_mode': g['input_mode'],
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
         'points': {u.uuid: u.points for u in g['players'] if not u.presenter},
         'players': {u.uuid: u.name for u in g['players'] if not u.presenter},
         'mute_players': g['mute_players'],
         }))


async def msg(str_msg, websocket):
    data = json.loads(str_msg)
    print(f"< {data}")
    if data['command'] == 'start_game':
        if 'name' in data and len(data['name']):
            websocket.name = html.escape(data['name'])
        # words = ' '.join(rrr.get_random_words(limit=5, maxLength=10))
        words = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
        game = {
            'host': websocket,
            'words': words,
            'players': [websocket],
            'offline_points': {},
            'previous': [],
            'current': None,
            'last_seen': None,
            'state': 'WAITING',
            'current_song': None,
            'help_percentage': int(data['help_percentage']) if 'help_percentage' in data else 0,
            'artist_only_chance': int(data['mc_chance_artist']) if 'mc_chance_artist' in data else 0,
            'title_only_chance': int(data['mc_chance_title']) if 'mc_chance_title' in data else 0,
            'input_mode': 'mc' if data['input_mode'] == 'mc' else 'input',
            'song_tags': data['song_tags'],
            'presentation_mode': data['presentation_mode'],
            'mute_players': data['mute_players'],

        }
        websocket.presenter = data['presentation_mode'] == True
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
        websocket.presenter = False
        if websocket.name in g['offline_points']:
            websocket.points = g['offline_points'][websocket.name]
        g['players'].append(websocket)
        websocket.game = g
        await broadcast_to_game(g, {'action': 'player_joined',
                                    'name': websocket.name,
                                    'uuid': websocket.uuid,
                                    'words': g['words'],
                                    'points': {u.uuid: u.points for u in g['players'] if not u.presenter},
                                    'players': {u.uuid: u.name for u in g['players'] if not u.presenter},
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
        if 'time' not in data['guess']:
            data['guess']['time'] = time.time()
        websocket.guess = data['guess']
        if "announce" in websocket.guess:
            data['guess']['time'] = time.time()
            await broadcast_to_game(websocket.game, {
                'action': 'player_guessed',
                'name': websocket.name,
                'uuid': websocket.uuid,
                'words': websocket.game['words']})

        all_players_guessed = True
        for p in websocket.game['players']:
            if not p.guess or "has_sent_guess" not in p.guess and not p.presenter:
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
                'text': 'Prepare for the next song!',
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
        # Select a new song (the yt_id has not been used in the current game before)
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
        for p in websocket.game['players']: # clear guesses
            p.guess = None

        reply = {'action': 'game_next',
                 'path': f'songs/game/{question_uuid}.mp3',
                 'result_yt_id': 'dQw4w9WgXcQ',
                 'words': g['words']}
        # Enrich reply
        if g['input_mode'] == 'mc':
            fixed_choices = get_fixed_choices(g, question) # multiple choices
            random.shuffle(fixed_choices)
            reply['fixed_choices'] = fixed_choices
        else:
            # Add help
            reply['help_artist'] = show_help(question['artist'], g['help_percentage'])
            reply['help_title'] = show_help(question['title'], g['help_percentage'])

        await broadcast_to_game(g, reply)
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
        if disable_adding:
            return await adding_disabled_message(websocket)
        yt = find_yt_urls(data['id'])
        await websocket.send(json.dumps({'action': 'show_progress', 'msg': 'Downloading song information'}))
        if not yt:
            await websocket.send(json.dumps({'action': 'showerror', 'msg': 'Failed to find song'}))
            return
        await websocket.send(json.dumps({'action': 'show_progress', 'msg': 'Downloading song...'}))
        song_uuid = str(uuid.uuid4())
        songpath = f'songs/tmp/{song_uuid}.mp3'
        for i in range(5):
            try:
                ffmpeg.input(yt['url'], t=20).output('public/' + songpath, codec='libmp3lame').run()
                break
            except ffmpeg.Error:
                print(f"Failed to download - retrying")
                await asyncio.sleep(5)
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
        if disable_adding:
            return await adding_disabled_message(websocket)
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
        for i in range(5):
            try:
                ffmpeg.input(song_tmp_path, t=f'{duration}ms', ss=f'{time_start}ms') \
                    .output(song_final_path, codec='libmp3lame').run()
                break
            except ffmpeg.Error:
                print(f"Failed to download - retrying")
                await asyncio.sleep(5)

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
            for i in range(5):
                try:
                    ffmpeg.input(yt['url'], t=60, ss=f'{time_start}ms').output(song_long_path, codec='libmp3lame').run()
                    break
                except ffmpeg.Error:
                    print(f"Failed to download - retrying")
                    await asyncio.sleep(5)
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

        await websocket.send(json.dumps({'action': 'show_stage', 'stage': 'song_init', 'yt_id_done': data['yt_id']}))
    elif data['command'] == 'find_song_suggestions':
        if disable_adding:
            return await adding_disabled_message(websocket)
        sqlite_cur.execute(f'SELECT title, artist FROM songs WHERE lastfm_url IS NOT NULL ORDER BY RANDOM() LIMIT 3')
        suggestions = []
        for row in sqlite_cur.fetchall():
            track = lastfm_network.get_track(row['artist'], row['title'])
            if track:
                # find some similar songs
                for st in track.get_similar(7):
                    suggestions.append(
                        tuple([st.item.artist.name, st.item.title, get_cover_image(st.item), st.item.get_url()]))
                # find more from artist
                for at in track.artist.get_top_tracks(7):
                    suggestions.append(
                        tuple([at.item.artist.name, at.item.title, get_cover_image(at.item), at.item.get_url()]))
        suggestions = list(set(suggestions))  # remove duplicates
        print("fetched", len(suggestions), "possible")
        artists = list(set([sug[0] for sug in suggestions]))
        artist_q = '?' + ',?' * (len(artists) - 1)

        sqlite_cur.execute(f'SELECT title, artist FROM songs WHERE artist IN ({artist_q})', artists)
        sugRem = []
        for row in sqlite_cur.fetchall():
            sugRem.append(tuple([row['artist'].lower(), row['title'].lower()]))
        print("Removing", len(sugRem))
        sugs = []
        for s in suggestions[:20]: # keep it somewhat short
            if tuple([s[0].lower(), s[1].lower()]) in sugRem:
                continue
            req = requests.get(s[3])
            x = lxhtml.fromstring(req.text)
            yt_url = x.xpath('//a[contains(@class,"play-this-track-playlink")][@data-youtube-url]/@data-youtube-url')
            yt_id = x.xpath('//a[contains(@class,"play-this-track-playlink")][@data-youtube-id]/@data-youtube-id')
            sugs.append({'artist': s[0], 'title': s[1], 'cover': s[2], 'lastfm_url': s[3],
                         'yt_url': yt_url[0] if yt_url else None,
                         'yt_id': yt_id[0] if yt_id else None,
                         })
        print(sugs)
        print("Found ", len(sugs))
        await websocket.send(
            json.dumps({'action': 'show_stage', 'stage': 'show_song_suggestions', 'suggestions': sugs}))
    else:
        greeting = f"Hello {data}!"

        await websocket.send(json.dumps({'msg': greeting}))
        print(f"> {greeting}")


async def adding_disabled_message(websocket):
    await websocket.send(json.dumps({'action': 'showerror', 'msg': 'Adding new songs is disabled for this instance'}))


def get_cover_image(track):
    try:
        return track.get_cover_image()
    except IndexError:
        return None

def get_fixed_choices(g, question):
    fixed_choices = []
    fixed_choices.append({'artist': question['artist'], 'title': question['title']})
    if len(g['song_tags']) == 0:
        if g['title_only_chance'] >= random.random() * 100:
            sqlite_cur.execute(f'SELECT distinct title FROM songs WHERE yt_id != ? AND title != ? AND artist = ? ORDER BY RANDOM() LIMIT 3', [question['yt_id'], question['title'], question['artist']])
            for row in sqlite_cur.fetchall():
                fixed_choices.append({'artist': question['artist'], 'title': row['title']})
                if len(fixed_choices) == 4:
                    return fixed_choices

        sqlite_cur.execute(f'SELECT songs.* FROM songs WHERE yt_id != ? AND title != ? ORDER BY RANDOM() LIMIT 3', [question['yt_id'], question['title']])
    else:
        params = g['song_tags'] + g['previous']
        tag_str = '?' + ',?' * (len(g['song_tags']) - 1)
        sqlite_cur.execute(
            f'SELECT songs.* FROM songs JOIN song_tags ON song_tags.song_uuid = songs.uuid AND song_tags.tag IN ({tag_str}) WHERE yt_id != ? AND title != ? ORDER BY RANDOM() LIMIT 1',
            params + [question['yt_id'], question['title']])
    for row in sqlite_cur.fetchall():
        fixed_choices.append({'artist': row['artist'], 'title': row['title']})
        if len(fixed_choices) == 4:
            break
    return fixed_choices



from serverhelper import migrate, find_yt_urls

sqlite_con.execute('''CREATE TABLE IF NOT EXISTS songs
               (yt_id text, uuid text, artist text, title text, time_created real, duration real,
                time_start real, client_ip text, lastfm_url text, lastfm_album text, lastfm_cover text)''')
sqlite_con.execute('''CREATE TABLE IF NOT EXISTS song_tags
               (song_uuid text, tag text, weight real)''')
sqlite_con.execute('''CREATE TABLE IF NOT EXISTS song_reports
               (song_uuid text, time_created text, client_ip text, type text)''')

migrate(sqlite_cur, sqlite_con, lastfm_network)
print("Starting...")
start_server = websockets.serve(handle, "0.0.0.0", 8765)

asyncio.get_event_loop().run_until_complete(start_server)
asyncio.get_event_loop().run_forever()

sqlite_con.close()
