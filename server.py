import asyncio
import html
import os
import traceback

import websockets
import ffmpeg
import json
import youtube_dl
import uuid
from tinydb import TinyDB, Query
import re
import random
from random_word import RandomWords
from Levenshtein import distance as levenshtein_distance
import time

not_quite_infinite = 9999999999999999999

db = TinyDB('db.json')

GAMES = {}
rrr = RandomWords()


async def handle(websocket, path):
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
                    if not p.guess:
                        all_players_guessed = False
                        break
                if all_players_guessed:  # next
                    await game_show_result(websocket.game)

        pass


async def broadcast_to_game(g, message):
    if g['players']:
        for user in g['players']:
            await user.send(json.dumps(message))


async def finish_game(g):
    pass


async def game_show_result(g):
    QQ = Query()
    current_question = db.search((QQ.type == 'song') & (QQ.uuid == g['current_song']))[0]
    exp_title = re.sub(r'[^a-z0-9]+', '', current_question['title'].lower())
    exp_artist = re.sub(r'[^a-z0-9]+', '', current_question['artist'].lower())

    g['state'] = 'results'
    results = []
    artist_dists = {}
    title_dists = {}
    for p in g['players']:
        a_dist = not_quite_infinite
        t_dist = not_quite_infinite
        if p.guess:
            a_dist = levenshtein_distance(exp_artist, re.sub(r'[^a-z0-9]+', '', p.guess['artist'].lower()))
            t_dist = levenshtein_distance(exp_title, re.sub(r'[^a-z0-9]+', '', p.guess['title'].lower()))

        guess = {
            'uuid': p.uuid,
            'artist': p.guess['artist'] if p.guess else '?',
            'title': p.guess['title'] if p.guess else '?',
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
    artist_points = {}
    last_dist = not_quite_infinite
    last_points = 0
    for p_uuid in artist_dists:
        if last_dist > artist_dists[p_uuid]:
            last_dist = artist_dists[p_uuid]
            last_points = last_points + 1
        artist_points[p_uuid] = last_points
    title_points = {}
    last_dist = not_quite_infinite
    last_points = 0
    for p_uuid in title_dists:
        if last_dist > title_dists[p_uuid]:
            last_dist = title_dists[p_uuid]
            last_points = last_points + 1
        title_points[p_uuid] = last_points

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
        await broadcast_to_game(websocket.game,
                                {'action': 'player_guessed', 'name': websocket.name, 'uuid': websocket.uuid,
                                 'words': websocket.game['words']})

        all_players_guessed = True
        for p in websocket.game['players']:
            if not p.guess:
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
        QQ = Query()
        questions = db.search(QQ.type == 'song')
        question = None
        for i in range(0, 10):
            potential_question = random.choice(questions)
            if potential_question['yt_id'] not in g['previous']:
                question = potential_question
                break
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
                                    'result_yt_id': 'dQw4w9WgXcQ',
                                    'words': g['words']})

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
            json.dumps({'action': 'show_stage', 'stage': 'song_prepare', 'title': yt['title'], 'file': songpath,
                        'yt_id': data['id'], 'uuid': song_uuid}))
    elif data['command'] == 'admin_list_songs':
        Q = Query()
        if data['password'] == os.getenv('ADMIN_PWD'):
            await websocket.send(
                json.dumps(
                    {'action': 'show_stage', 'stage': 'admin_show_songs', 'songs': db.search((Q.type == 'song'))}))
    elif data['command'] == 'report_song':
        song_uuid = re.sub(r'[^a-zA-Z0-9\-]+', '', data['uuid'])
        Q = Query()
        vote_positive = data['votetype'] == 'plus'
        if not db.search((Q.type == 'song') & (Q.uuid == song_uuid)):
            raise Exception('Song not found')
        if db.search((Q.type == 'vote') & (Q.song_uuid == song_uuid) & (
                Q.client_ip == (websocket.request_headers.get('X-Forwarded-For') or websocket.remote_address[0]))):
            return
        db.insert({
            'type': 'vote',
            'song_uuid': song_uuid,
            'vote_type': vote_positive,
            'time_created': time.time(),
            'client_ip': websocket.request_headers.get('X-Forwarded-For') or websocket.remote_address[0],
        })

    elif data['command'] == 'init_add':
        print(data)
        song_uuid = re.sub(r'[^a-zA-Z0-9\-]+', '', data['uuid'])
        Q = Query()
        if db.search((Q.type == 'song') & (Q.uuid == song_uuid)):
            raise Exception('Already existing')
        print(data['uuid'])
        print(song_uuid)
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

        db.insert({'type': 'song',
                   'yt_id': data['yt_id'],
                   'uuid': song_uuid,
                   'artist': data['artist'],
                   'title': data['title'],
                   'tags': data['tags'],
                   'time_created': time.time(),
                   'time': duration,
                   'time_start': time_start,
                   'client_ip': websocket.request_headers.get('X-Forwarded-For') or websocket.remote_address[0],
                   })

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
    songs = db.search(QQ.type == 'song')
    gamedir = 'public/songs/game/'
    for s in songs:
        path = gamedir + s['yt_id'] + '.mp3'
        if not os.path.isfile(path):
            print("Migrating by downloading long file to " + path)
            starttime = s['time_start'] if 'time_start' in s else 0
            yt = find_yt_urls(s['yt_id'])
            if yt:
                song_long_path = 'public/songs/game/' + s['yt_id'] + '.mp3'
                ffmpeg.input(yt['url'], t=60, ss=f'{starttime}ms').output(song_long_path, codec='libmp3lame').run()


migrate()
print("Starting...")
start_server = websockets.serve(handle, "0.0.0.0", 8765)

asyncio.get_event_loop().run_until_complete(start_server)
asyncio.get_event_loop().run_forever()
