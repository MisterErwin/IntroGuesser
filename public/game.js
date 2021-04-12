// const socket = new WebSocket('ws://localhost:8765');
const socket = new WebSocket(
    (location.hostname === "localhost" || location.hostname === "127.0.0.1") ?
        'ws://localhost:8765' :
        'wss://introguesserws.example.org');

socket.addEventListener('close', function (event) {
    document.body.classList.add("bg-danger");
    setTimeout(function () {
        location.reload()
    }, 1000);
});
socket.addEventListener('open', function (event) {
    let urlParams = new URLSearchParams(window.location.search);
    if (urlParams.has('r'))
        document.getElementById('join_game_words').value = decodeURIComponent(urlParams.get('r'));
});


let addSongData;
let myUUID;
let currentGame = undefined;
let resultNode;
// Listen for messages
socket.addEventListener('message', function (event) {
    const data = JSON.parse(event.data);
    console.log('Message from server ', data);

    if (data.action === 'show_progress') {
        progressModal.show();
        document.getElementById("progressModalBody").innerText = data.msg;
    } else if (data.action === 'showerror') {
        $(".click-one").removeAttr('disabled');
        progressModal.hide();
        errorModal.show();
        document.getElementById("errorModalBody").innerText = data.msg;
    } else if (data.action === 'welcome') {
        document.getElementById('user_name').value = data.name;
        $("#main-loading").hide();
        $("#main-screen").show();
        myUUID = data.uuid;
    } else if (data.action === 'player_guessed') {
        $('[data-player-uuid=' + data.uuid + '] a').addClass("text-info");
        if (currentGame.host && !currentGame.voteTimeTimeout) {
            socket.send(JSON.stringify({command: 'game_force_vote', 'time': 30}));
            currentGame.voteTimeTimeout = setTimeout(function () {
                socket.send(JSON.stringify({command: 'game_force_vote', 'time': 0}));
            }, 30 * 1000);
        }
    } else if (data.action === 'player_request_continue') {
        $('[data-player-uuid=' + data.uuid + '] a').addClass("text-info");
        if (currentGame.host && !currentGame.resultsListenTimeTimeout) {
            socket.send(JSON.stringify({command: 'game_force_next_round', 'time': 30}));
            currentGame.resultsListenTimeTimeout = setTimeout(function () {
                socket.send(JSON.stringify({command: 'game_next'}));
            }, 30 * 1000);
        }
    } else if (data.action === 'player_left') {
        $('[data-player-uuid=' + data.uuid + ']  ').remove();
    } else if (data.action === 'game_progress_bar') {
        document.getElementById('gameProgressBar').style.width = data['value'] + '%';
        document.getElementById('gameProgressBar').style.transition = 'width ' + data['time'] + 's linear';
    } else if (data.action === 'results_progress_bar') {
        document.getElementById('resultsProgressBar').style.width = data['value'] + '%';
        document.getElementById('resultsProgressBar').style.transition = 'width ' + data['time'] + 's linear';
    } else if (data.action === 'game_next') {
        if (currentGame.voteTimeTimeout) {
            window.clearTimeout(currentGame.voteTimeTimeout);
            currentGame.voteTimeTimeout = null;
        }
        if (currentGame.resultsListenTimeTimeout) {
            window.clearTimeout(currentGame.resultsListenTimeTimeout);
            currentGame.resultsListenTimeTimeout = null;
        }
        $(".click-one").removeAttr('disabled');
        document.getElementById('game-screen-results-video').src = '';
        if (resultNode)
            resultNode.stop(0);
        playNote(261.6, 'sine')
        $("main").hide();
        $("#game-screen-playing").show();
        currentGame.path = data.path;
        document.getElementById('gameArtist').value = "";
        document.getElementById('gameTitle').value = "";
        $("#gameGuessButton").removeClass("btn-success").addClass("btn-primary");
        $("[data-player-uuid] a").removeClass("text-info");

        document.getElementById('gameProgressBar').style.width = '0%';
        document.getElementById('gameProgressBar').style.transition = 'initial';
        loadIntoBuffer(currentGame.path, function () {
            playSound(setupBuffer)
        });

    } else if (data.action === 'show_stage') {
        $(".click-one").removeAttr('disabled');

        $("main").hide();
        progressModal.hide();
        switch (data.stage) {
            case 'game_results':
                playNote(261.6, 'sine')
                $("#game-screen-results").show();
                $("#game-screen-results-title").text(data.title);
                $("#game-screen-results-artist").text(data.artist);

                document.getElementById('resultsProgressBar').style.width = '0%';
                document.getElementById('resultsProgressBar').style.transition = 'initial';


                document.getElementById('game-screen-results-video').src = 'https://www.youtube-nocookie.com/embed/' + data.yt_id;

                loadIntoBuffer(data.long_file, function (b) {
                    // Play the long variant and fade to zero in the last few seconds
                    let gain = audioContext.createGain();
                    gain.connect(getMasterGain())
                    resultNode = playSound(b, gain);
                    gain.gain.setValueAtTime(1, audioContext.currentTime + 52);
                    gain.gain.exponentialRampToValueAtTime(.001, audioContext.currentTime + 59);
                })

                const tbody = $("#game-screen-results-tbody");
                tbody.html("");
                for (let i in data.guesses) {
                    if (!data.guesses.hasOwnProperty(i)) continue;
                    const guess = data.guesses[i];
                    let $tr = $("<tr/>");
                    $tr.appendTo(tbody);
                    $("<td/>", {text: currentGame.players[guess.uuid]}).appendTo($tr);
                    $("<td/>", {
                        text: guess.title
                            + ' (' + (guess.uuid in data.title_points ? data.title_points[guess.uuid] : 0) + ')'
                    }).appendTo($tr);
                    $("<td/>", {
                        text: guess.artist
                            + ' (' + (guess.uuid in data.artist_points ? data.artist_points[guess.uuid] : 0) + ')'
                    }).appendTo($tr);
                }

                let gameSidebarPlayersDiv = document.getElementById('gameSidebarPlayers');
                gameSidebarPlayersDiv.innerHTML = "";
                currentGame.points = data.points;
                currentGame.song_uuid = data.song_uuid;
                updatePlayerSidebar(currentGame.players, data.points, gameSidebarPlayersDiv);

                break;
            case 'join_game':
                $("#addStuffButton").hide();

                playNote(161.6, 'sine')
                document.getElementById('nav_room_code').value = data.words;
                currentGame = data;
                document.getElementById('gameSidebar').setAttribute('style', 'display:fixed !important');
                if (data.state === 'WAITING') {
                    $("#game-screen-waiting").show();
                } else if (data.state === 'playing') {
                    $("#game-screen-playing").show();
                } else if (data.state === 'results') {
                    $("#game-screen-results").show();
                } else {
                    alert("Unknown game state " + data.state);
                }
                window.history.pushState({}, '', window.location.protocol + "//" + window.location.host + window.location.pathname + '?r=' + encodeURIComponent(data.words));

                if (currentGame.path) {
                    loadIntoBuffer(currentGame.path, function () {
                        playSound(setupBuffer)
                    });
                }

                let gameSidebarPlayers = document.getElementById('gameSidebarPlayers');
                gameSidebarPlayers.innerHTML = "";

                updatePlayerSidebar(data.players, data.points, gameSidebarPlayers);

                if (currentGame.host) {
                    $(".show-host").show();
                    $(".show-non-host").hide();
                } else {
                    $(".show-host").hide();
                    $(".show-non-host").show();
                }

                break;
            case 'song_init':
                $("#main-setup-1").show();
                break;
            case 'song_prepare':
                $("#main-setup-2").show();
                // document.getElementById("setupPlayerSrc").src = data.file
                loadIntoBuffer(data.file, function (audioBuffer) {
                    setupPeaks(audioBuffer);
                });

                // document.getElementById("setupPlayer").load();
                document.getElementById("setupTitleShow").innerText = data.title;
                document.getElementById("setupPlayerArtist").value = "";
                document.getElementById("setupPlayerTitle").value = "";

                addSongData = data;
                break;
            case 'admin_show_songs':
                $("#main-song-list").show();
                const songsTBody = $("#song_list_table");
                songsTBody.html("");
                for (let i in data.songs) {
                    let s = data.songs[i];
                    let $tr = $("<tr/>");
                    $tr.appendTo(songsTBody);
                    $("<td/>", {text: s.title}).appendTo($tr);
                    $("<td/>", {text: s.artist}).appendTo($tr);
                    $("<td/>", {text: s.time}).appendTo($tr);

                    $("<td/>", {text: ''}).appendTo($tr)
                        .append($("<a/>", {
                            class: 'btn btn-sm btn-secondary',
                            target: '__blank',
                            text: 'YT',
                            href: 'https://www.youtube.com/watch?v=' + s.yt_id
                        }))
                        .append($("<a/>", {
                            class: 'btn btn-sm btn-secondary',
                            text: 'intro',
                            'data-admin-play-intro': 'songs/game/' + s.uuid + '.mp3'
                        }))

                    ;

                }

                break;
            default:
                console.error('Unknown stage')
        }
    } else if (data.action === 'player_joined') {
        if (!currentGame) return;
        const gameSidebarPlayers = document.getElementById('gameSidebarPlayers');
        gameSidebarPlayers.innerHTML = "";
        updatePlayerSidebar(data.players, data.points, gameSidebarPlayers);
    } else {
        console.error("hm?");
    }
});

function updatePlayerSidebar(players, points, gameSidebarPlayersUl) {
    currentGame.players = players;
    for (let gameuuid in players) {
        if (!players.hasOwnProperty(gameuuid)) continue;
        let li = $("<li/>", {class: 'nav-item text-secondary', 'data-player-uuid': gameuuid});
        li.appendTo(gameSidebarPlayersUl);
        $("<a/>", {
            'href': '#', 'class': 'nav-link', 'text': players[gameuuid] +
                ' ' +
                (gameuuid in points ? ('[' + points[gameuuid] + ']') : '[-]')
                + (gameuuid === myUUID ? " (you) " : "")
        })
            .appendTo(li);
    }
}

const progressModal = new bootstrap.Modal(document.getElementById('progressModal'), {
    backdrop: 'static',
    'keyboard': false
});
const errorModal = new bootstrap.Modal(document.getElementById('errorModal'), {
    backdrop: 'static',
    close: 'true',
})

$("#new_song_next").on('click', function () {
    const vid = document.getElementById('new_song_watch');
    socket.send(JSON.stringify({'command': 'init_download', 'id': vid.value}));
});
$("#song_report_bad").on('click', function () {
    $("#song_report_bad,#song_report_good").attr("disabled", "disabled")
    if (currentGame.song_uuid)
        socket.send(JSON.stringify({'command': 'report_song', 'uuid': currentGame.song_uuid, 'votetype': 'minus'}));
});
$("#song_report_good").on('click', function () {
    $("#song_report_bad,#song_report_good").attr("disabled", "disabled")
    if (currentGame.song_uuid)
        socket.send(JSON.stringify({'command': 'report_song', 'uuid': currentGame.song_uuid, 'votetype': 'plus'}));
});

$("#setupAddButton").on('click', function () {
    const d = {
        'command': 'init_add',
        'yt_id': addSongData.yt_id,
        'uuid': addSongData.uuid,
        'artist': document.getElementById("setupPlayerArtist").value,
        'title': document.getElementById("setupPlayerTitle").value,
        'tags': document.getElementById("setupPlayerTags").value,
        'time_start': document.getElementById("setupPlayerTimeStart").value,
        'time_end': document.getElementById("setupPlayerTimeEnd").value,

    }
    console.log(d)
    socket.send(JSON.stringify(d));
});


$("#join_game_button").on('click', function () {
    socket.send(JSON.stringify({
        'command': 'join_game',
        'words': document.getElementById('join_game_words').value,
        'name': document.getElementById('user_name').value
    }));
});

$("#start_new_game_button").on('click', function () {
    socket.send(JSON.stringify({
        'command': 'start_game',
        'words': document.getElementById('join_game_words').value,
        'name': document.getElementById('user_name').value
    }));
});

$("#gameWaitingStart").on('click', function () {
    socket.send(JSON.stringify({command: 'game_next'}))
});


$("#gameResultsButton").on('click', function () {
    socket.send(JSON.stringify({command: 'game_next'}))
});
$("#gameResultsRequestButton").on('click', function () {
    socket.send(JSON.stringify({command: 'game_next_req'}))
});


$("#gamePlayButton").on('click', function () {
    if (currentGame)
        loadIntoBuffer(currentGame.path, function () {
            playSound(setupBuffer)
        });
});

$("#gameGuessButton").on('click', function () {
    socket.send(JSON.stringify({
        command: 'game_set_guess',
        guess: {
            artist: document.getElementById('gameArtist').value,
            title: document.getElementById('gameTitle').value,
        },
    }))
    $(this).removeClass("btn-primary").addClass("btn-success")
});

$("#nav_room_code_btn").on('click', function () {
    let room_code = document.getElementById('nav_room_code').value;
    let copyText = document.querySelector("#nav_room_code");
    copyText.value = window.location.protocol + "//" + window.location.host + window.location.pathname + '?r=' + encodeURIComponent(room_code);
    copyText.select();
    document.execCommand("copy");
    copyText.value = room_code;

})

$("tbody").on('click', '[data-admin-play-intro]', function () {
    loadIntoBuffer($(this).attr("data-admin-play-intro"), playSound);
});


let totalTime, endTime, progressBar;

function updateProgressBar() {
    if (!endTime) return;
    const diff = endTime - new Date().getTime();
    const percentage = (1 - diff / totalTime) * 100;
    progressBar.style.width = percentage + '%';
    window.requestAnimationFrame(updateProgressBar)
}


window.AudioContext = window.AudioContext || window.webkitAudioContext;
let audioContext = new AudioContext();
let setupBuffer = null;

let _masterGain = null;

function getMasterGain() {
    if (!_masterGain) {
        _masterGain = audioContext.createGain();
        _masterGain.connect(audioContext.destination);
        const elem = document.getElementById('masterVolume');

        function update() {
            _masterGain.gain.value = parseFloat(elem.value) / 100;
        }

        elem.addEventListener('input', update);
        update();
    }

    return _masterGain;
}

function loadIntoBuffer(url, cb) {
    fetch(url)
        .then(function (resp) {
            return resp.arrayBuffer();
        })
        .then(function (buffer) {
            return audioContext.decodeAudioData(buffer);
        })
        .then(function (audioBuffer) {
            setupBuffer = audioBuffer;
            if (cb) cb(audioBuffer);
        });
}

function playSound(buffer, connectTo) {
    const source = audioContext.createBufferSource();
    source.buffer = buffer;                    // tell the source which sound to play
    source.connect(connectTo ? connectTo : getMasterGain());
    source.start(0);                           // play the source now
    return source;
}

function playNote(frequency, type) {
    let o = audioContext.createOscillator();
    g = audioContext.createGain();
    o.type = type;
    o.connect(g);
    o.frequency.value = frequency;
    g.connect(getMasterGain());
    o.start(0);
    g.gain.exponentialRampToValueAtTime(0.00001, audioContext.currentTime + 1)
}

$(".click-one").on('click', function () {
    $(".click-once").attr('disabled', 'disabled');
})


function showAdmin(pwd) {
    if (!pwd) {
        pwd = prompt('Please enter the password');
        if (!pwd) return;
    }
    socket.send(JSON.stringify({
        command: 'admin_list_songs',
        password: pwd
    }));

}