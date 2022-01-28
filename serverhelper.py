import youtube_dl
from pylast import WSError
from tinydb import TinyDB, Query
import os
import ffmpeg


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


def migrate(sqlite_cur, sqlite_con, lastfm_network):
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


def fetch_last_fm(data, lastfm_track, uuid):
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

