// const socket = new WebSocket('ws://localhost:8765');
const socket = new WebSocket(
  (
    (location.hostname === "localhost" || location.hostname === "127.0.0.1") ?
      'ws://localhost:8765' :
      (location.hostname === "intro.guesser" ? 'ws://introserv.guesser:8765' :
        'wss://introguesserws.cloud.luepg.es'))
  + '/version/1.2.1'
);

socket.addEventListener('close', function (event) {
  document.body.classList.add("bg-danger");
  setTimeout(function () {
    location.reload()
  }, 1000);
});
socket.addEventListener('open', function (event) {
  let urlParams = new URLSearchParams(window.location.search);
  if (urlParams.has('r')) {
    document.getElementById('join_game_words').value = decodeURIComponent(urlParams.get('r'));
    $("#join_game_words").parent().parent().hide();
  }
});


let addSongData;
let myUUID;
let currentGame = undefined;
let resultNode;
let guessNode;
let adminSongs;
let dataSaveMode = false;
// Listen for messages
socket.addEventListener('message', function (event) {
  const data = JSON.parse(event.data);
  console.log('Message from server ', data);

  if (data.action === 'show_progress') {
    progressModal.show();
    document.getElementById("progressModalBody").innerText = data.msg;
  } else if (data.action === 'showerror') {
    $(".click-once").removeAttr('disabled');
    progressModal.hide();
    errorModal.show();
    document.getElementById("errorModalBody").innerText = data.msg;
  } else if (data.action === 'welcome') {
    // User name from local storage or random
    document.getElementById('user_name').value = window.localStorage.hasOwnProperty("intro_user_name") ?
      window.localStorage.getItem("intro_user_name") : data.name;
    $("#main-loading").hide();
    $("#main-screen").show();
    myUUID = data.uuid;
    if (!data.allow_adding)
      $("#addStuffButton").hide();
  } else if (data.action === 'player_guessed') {
    $('[data-player-uuid=' + data.uuid + '] a').addClass("text-info");
    if (currentGame.host && !currentGame.voteTimeTimeout) {
      const timeToGuess = parseInt($("#newGameSettingsGuessTime").val());
      socket.send(JSON.stringify({command: 'game_force_vote', 'time': timeToGuess}));
      currentGame.voteTimeTimeout = setTimeout(function () {
        socket.send(JSON.stringify({command: 'game_force_vote', 'time': 0}));
      }, (timeToGuess + 1) * 1000);
    }
  } else if (data.action === 'player_request_continue') {
    $('[data-player-uuid=' + data.uuid + '] a').addClass("text-info");
    if (currentGame.host && !currentGame.resultsListenTimeTimeout) {
      let skippingN = $('[data-player-uuid] a.text-info').length;
      const skipPercentage = Math.min(99, parseInt($("#newGameSettingsSkipPercentage").val()));
      // Only skip of enough people are of this opinion
      if ((skippingN / Object.keys(currentGame.players).length * 100) > skipPercentage) {
        const skipDuration = parseInt($("#newGameSettingsSkipDuration").val());
        $("#gameResultsRequestButton").hide();
        $("#gameResultsButton").show();
        socket.send(JSON.stringify({command: 'game_force_next_round', 'time': skipDuration}));
        currentGame.resultsListenTimeTimeout = setTimeout(function () {
          socket.send(JSON.stringify({command: 'game_next'}));
        }, skipDuration * 1000);
      }
    }
  } else if (data.action === 'player_left') {
    $('[data-player-uuid=' + data.uuid + '] a ').addClass("text-secondary");
    delete currentGame.players[data.uuid];
  } else if (data.action === 'game_progress_bar') {
    document.getElementById('gameProgressBar').style.width = data['value'] + '%';
    document.getElementById('gameProgressBar').style.transition = 'width ' + data['time'] + 's linear';
  } else if (data.action === 'results_progress_bar') {
    if (data['text'])
      document.getElementById('resultsProgressBar').textContent = data['text'];
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
    $(".click-once").removeAttr('disabled');
    document.getElementById('game-screen-results-video').src = '';
    document.getElementById('game-screen-results-image').src = '';

    if (data.fixed_choices && data.fixed_choices.length > 1) {
      currentGame.fixed_choices = data.fixed_choices;
      $("#gamePlayFixedInputs").show();
      $("#gamePlayInput").hide();
      for (let i = 0; i < 4; i++) {
        $("#gameGuessButtonFixed" + i).data('title', data.fixed_choices[i].title)
          .data('artist', data.fixed_choices[i].artist)
          .text(data.fixed_choices[i].title + " - " + data.fixed_choices[i].artist)
          .removeClass("btn-info")
          .addClass("btn-primary");
      }
    } else {
      $("#gamePlayInput").show();
      $("#gamePlayFixedInputs").hide();
      $("#gameArtist").attr('placeholder', data.help_artist);
      $("#gameTitle").attr('placeholder', data.help_title);
    }

    if (resultNode)
      resultNode.stop(0);
    // playNote(261.6, 'sine')
    $("main").hide();
    $("#game-screen-playing").show();
    currentGame.path = data.path;
    document.getElementById('gameArtist').value = "";
    document.getElementById('gameTitle').value = "";
    $("#gameGuessButton").removeClass("btn-success").addClass("btn-primary");
    $("[data-player-uuid] a").removeClass("text-info");

    document.getElementById('gameProgressBar').style.width = '0%';
    document.getElementById('gameProgressBar').style.transition = 'initial';
    if (!dataSaveMode)
      loadIntoBuffer(currentGame.path, function () {
        guessNode = playSound(setupBuffer)
      });

    currentGame.autoSaveGuessTimer = window.setInterval(function () {
      sendGuess(false);
    }, 1000);
  } else if (data.action === 'reply_fetch_tags') {
    let tagSelect = $("#newGameSettingsTags");
    tagSelect.html("");
    for (let tag in data.tags) {
      $("<option/>", {
        text: data.tags[tag].tag + " (" + data.tags[tag].songs + " songs)",
        value: data.tags[tag].tag
      }).appendTo(tagSelect);
    }
  } else if (data.action === 'show_stage') {
    if (currentGame && currentGame.autoSaveGuessTimer) {
      window.clearInterval(currentGame.autoSaveGuessTimer);
      currentGame.autoSaveGuessTimer = null;
    }
    $(".click-once").removeAttr('disabled');
    $("[data-song-report-button]").removeAttr("disabled");

    $("main").hide();
    progressModal.hide();
    switch (data.stage) {
      case 'game_results':
        // playNote(261.6, 'sine')
        $("#game-screen-results").show();
        $("#game-screen-results-title").text(data.title);
        $("#game-screen-results-artist").text(data.artist);

        has_sent_guess = false;

        document.getElementById('resultsProgressBar').textContent = '';
        document.getElementById('resultsProgressBar').style.width = '0%';
        document.getElementById('resultsProgressBar').style.transition = 'initial';

        $("#gameResultsRequestButton").show();
        $("#gameResultsButton").hide();

        if (dataSaveMode) {
          $("#game-screen-results-image").hide();
          $("#game-screen-results-video").hide();
        } else if (data['cover_image']) {
          $("#game-screen-results-image").show();
          $("#game-screen-results-video").hide();
          document.getElementById('game-screen-results-image').src = data['cover_image'];
        } else {
          $("#game-screen-results-image").hide();
          $("#game-screen-results-video").show();
          document.getElementById('game-screen-results-video').src = 'https://www.youtube-nocookie.com/embed/' + data.yt_id;
        }

        if (guessNode)
          guessNode.stop(0);

        if (!dataSaveMode)
          loadIntoBuffer(data.long_file, function (b) {
            if (resultNode)
              resultNode.stop(0);
            // Play the long variant and fade to zero in the last few seconds
            let gain = audioContext.createGain();
            gain.connect(getMasterGain())
            resultNode = playSound(b, gain);
            gain.gain.setValueAtTime(1, audioContext.currentTime + 52);
            gain.gain.exponentialRampToValueAtTime(.001, audioContext.currentTime + 59);
          })

        //
        const showAsMC = data['display_mode'] === 'mc';
        const mcResultsRow = $("#game-screen-results-mc");
        if (showAsMC && currentGame.fixed_choices) {
          $("#game-screen-results-table").hide();
          mcResultsRow.show();
          mcResultsRow.html(null);

          for (let choice of currentGame.fixed_choices) {
            // For every possible choice, create a card
            const correct = choice.title === data.title && choice.artist === data.artist;
            let $card = $("<div/>", {class: 'card me-3 ' + (correct ? 'border-success' : ''), style: 'width: 18rem'})
              .appendTo(mcResultsRow);
            // Have the body with title and artist
            let $cbody = $("<div/>", {class: 'card-body'}).appendTo($card);
            $("<h5/>", {class: 'card-title', text: choice.title}).appendTo($cbody);
            $("<h5/>", {class: 'card-title', text: choice.artist}).appendTo($cbody);

            // And a list with the guesses
            let $ul = $("<ul/>", {class: 'list-group list-group-flush ' + (correct ? '' : 'border-danger')}).appendTo($card);

            for (let guess of data.guesses) {
              if (guess.title === choice.title && guess.artist === choice.artist) {
                let $guessLi = $("<li/>", {class: 'list-group-item', text: currentGame.players[guess.uuid]})
                  .appendTo($ul);
                let playerPoints = data.title_points[guess.uuid];
                if (playerPoints)
                  $("<span/>", {
                    text: '+' + playerPoints,
                    class: "badge bg-success rounded-pill ms-2"
                  }).appendTo($guessLi);
              }
            }

          }

        } else {
          $("#game-screen-results-table").show();
          mcResultsRow.hide();

          const tbody = $("#game-screen-results-tbody");
          tbody.html("");

          for (let i in data.guesses) {
            if (!data.guesses.hasOwnProperty(i)) continue;
            const guess = data.guesses[i];
            let $tr = $("<tr/>");
            $tr.appendTo(tbody);
            if (showAsMC) {
              let $titleTD = $("<td/>", {text: currentGame.players[guess.uuid]});
              console.log(guess.uuid in data.title_points);
              if (guess.uuid in data.title_points) {
                let playerPoints = data.title_points[guess.uuid];
                if (playerPoints)
                  $("<span/>", {
                    text: '+' + playerPoints,
                    class: "badge bg-success rounded-pill ms-2"
                  }).appendTo($titleTD);
              }
              $titleTD.appendTo($tr);
              $("<td/>", {
                text: guess.title
              }).appendTo($tr);
              $("<td/>", {
                text: guess.artist
              }).appendTo($tr);
            } else {
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
          }
        }


        let gameSidebarPlayersDiv = document.getElementById('gameSidebarPlayers');
        currentGame.points = data.points;
        currentGame.song_uuid = data.song_uuid;
        updatePlayerSidebar(currentGame.players, data.points, gameSidebarPlayersDiv);

        break;
      case 'join_game':
        $("#addStuffButton").hide();

        if (data['mute_players'] && !data.host)
          $("#btn_wifi_toggle[value='wifi']").click();

        // playNote(161.6, 'sine')
        document.getElementById('nav_room_code').value = data.words;
        currentGame = data;
        document.getElementById('gameSidebar').setAttribute('style', 'display:fixed !important');
        if (data.state === 'WAITING') {
          $("#game-screen-waiting").show();
        } else if (data.state === 'playing') {
          if (data.fixed_choices && data.fixed_choices.length > 1) {
            currentGame.fixed_choices = data.fixed_choices;
            $("#gamePlayFixedInputs").show();
            $("#gamePlayInput").hide();
            for (let i = 0; i < 4; i++) {
              $("#gameGuessButtonFixed" + i).data('title', data.fixed_choices[i].title)
                .data('artist', data.fixed_choices[i].artist)
                .text(data.fixed_choices[i].title + " - " + data.fixed_choices[i].artist)
                .removeClass("btn-info")
                .addClass("btn-primary");
            }
          } else {
            $("#gamePlayInput").show();
            $("#gamePlayFixedInputs").hide();
            $("#gameArtist").attr('placeholder', data.help_artist);
            $("#gameTitle").attr('placeholder', data.help_title);
          }

          $("#game-screen-playing").show();
        } else if (data.state === 'results') {
          $("#game-screen-results").show();
        } else {
          alert("Unknown game state " + data.state);
        }
        window.history.pushState({}, '', window.location.protocol + "//" + window.location.host + window.location.pathname + '?r=' + encodeURIComponent(data.words));

        if (currentGame.path && !dataSaveMode) {
          loadIntoBuffer(currentGame.path, function () {
            guessNode = playSound(setupBuffer)
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
        document.getElementById("setupPlayerArtist").value = "";
        document.getElementById("setupPlayerTitle").value = "";
        if (data['yt_id_done']) {
          showToast('Added song', 'Successfully added that song');
          let ytbtn = $('[data-ytid="' + data['yt_id_done'] + '"]');
          ytbtn.text("Successfully added").removeClass("btn-primary")
            .addClass("btn-secondary").attr("disabled");
          ytbtn.parent().parent().addClass("bg-success");
        }
        break;
      case 'song_get_data':
        $("#main-setup-2").show();
        // document.getElementById("setupPlayerSrc").src = data.file


        // document.getElementById("setupPlayer").load();
        document.getElementById("setupTitleShow").innerText = data.title;

        addSongData = data;
        break;
      case 'song_prepare':
        $("#main-setup-3").show();

        loadIntoBuffer(addSongData.file, function (audioBuffer) {
          setupPeaks(audioBuffer);
        });

        if (data.error) {
          alert(data.error);
        }
        document.getElementById("setupPlayerAlbum").value = data.lastfm_album;
        document.getElementById("setupPlayerImage").src = data.lastfm_cover;
        document.getElementById("setupPlayerTags").value = data.lastfm_tags ? (data.lastfm_tags.map(function (e) {
          return e.tag
        }).join(', ')) : ' - ';


        Object.assign(addSongData, data);
        console.log(addSongData)
        break;
      case 'show_song_suggestions':
        $("#main-setup-suggestions").show();
        $("#new_song_suggestions_first").hide();
        $("#new_song_suggestions_repeat").show();

        let cardsGroup = $("#main-setup-suggestions_cards");
        cardsGroup.html("");
        for (let sug of data.suggestions) {
          let card = $("<div/>", {
            class: 'card',
            style: 'width: 18rem'
          }).appendTo($("<div/>", {class: 'col'}).appendTo(cardsGroup));
          $("<img/>", {
            src: sug['cover'],
            class: 'card-img-top',
            style: 'width: 18rem; height: 18rem; background: grey;'
          }).appendTo(card);
          let cardBody = $("<div/>", {class: 'card-body'}).appendTo(card);
          $("<h5/>", {class: 'card-title', text: sug['artist'] + " - " + sug['title']}).appendTo(cardBody)
          if (sug['yt_url'])
            $("<a/>", {
              class: 'card-link',
              text: 'Listen',
              'target': '__blank',
              'href': sug['yt_url']
            }).appendTo(cardBody);
          else
            $("<a/>", {
              class: 'card-link',
              text: 'More',
              'target': '__blank',
              'href': sug['lastfm_url']
            }).appendTo(cardBody);

          $("<br/>").appendTo(cardBody);
          $("<btn/>", {
            class: 'btn btn-primary suggestion-song-card-btn',
            text: 'Add as into',
            'data-title': sug['title'],
            'data-artist': sug['artist'],
            'data-yturl': sug['yt_url'],
            'data-ytid': sug['yt_id'],
          }).appendTo(cardBody);
        }
        $('[data-action="new_song_suggestions"]').removeAttr('disabled');
        break;
      case 'admin_show_songs':
        $("#main-song-list").show();
        const songsTBody = $("#song_list_table");
        songsTBody.html("");
        adminSongs = {};
        for (let i in data.songs) {
          let s = data.songs[i];
          if (adminSongs.hasOwnProperty(s.uuid)) {
            adminSongs[s.uuid].tags.push({tag: s.tag, weight: s.weight});
          } else {
            adminSongs[s.uuid] = s;
            adminSongs[s.uuid].tags = [];
            if (s.tag)
              adminSongs[s.uuid].tags.push({tag: s.tag, weight: s.weight});
          }
        }
        for (let uuid in adminSongs) {
          let s = adminSongs[uuid];
          let $tr = $("<tr/>", {'data-song-uuid': uuid});
          $tr.appendTo(songsTBody);
          $("<td/>", {text: s.title}).appendTo($tr);
          $("<td/>", {text: s.artist}).appendTo($tr);
          $("<td/>", {text: s.duration}).appendTo($tr);
          $("<td/>", {text: s.count_like + " / " + s.count_bad + " / " + s.count_wrong}).appendTo($tr);


          let $td = $("<td/>", {text: ''}).appendTo($tr)
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

          if (s.lastfm_url) {
            $td.append($("<a/>", {
              class: 'btn btn-sm btn-info',
              text: 'last.fm',
              target: '__blank',
              href: s.lastfm_url,
            }))
          }

          $td = $("<td/>", {text: ''}).appendTo($tr);
          let $div = $("<div/>", {class: 'collapse', 'id': 'song_admin_tags_uuid_' + s.uuid});
          if (s.tags) {
            s.tags.sort((a, b) => (a.weight < b.weight) ? 1 : ((b.weight < a.weight) ? -1 : 0));
            let n_pops = 3;
            for (let tag_i in s.tags) {
              ((n_pops-- > 0) ? $td : $div).append($("<span/>", {
                class: 'badge bg-primary',
                text: s.tags[tag_i].tag + "(" + s.tags[tag_i].weight + ")",
                'data-admin-query-tag': s.tags[tag_i].tag,
              }));
            }
            if (n_pops <= 0) {
              $td.append($("<a/>", {
                class: 'badge bg-secondary',
                text: '+ ' + (n_pops * -1),
                'data-bs-toggle': "collapse",
                'data-bs-target': '#song_admin_tags_uuid_' + s.uuid
              }))
            }
          }
          $div.appendTo($td);
        }

        break;
      default:
        console.error('Unknown stage')
    }
  } else if (data.action === 'player_joined') {
    if (!currentGame) return;
    const gameSidebarPlayers = document.getElementById('gameSidebarPlayers');

    updatePlayerSidebar(data.players, data.points, gameSidebarPlayers);
  } else {
    console.error("hm?");
  }
});

/**
 * @param {{}} players
 * @param {string} points
 * @param {HTMLElement} gameSidebarPlayersUl
 */
function updatePlayerSidebar(players, points, gameSidebarPlayersUl) {
  currentGame.players = players;

  let existingNodes = {};
  const liElementContainer = document.createDocumentFragment();

  // Move elements to the fragment and store them
  let childLen;
  while ((childLen=gameSidebarPlayersUl.children.length) > 0) {
    let playerEntry = gameSidebarPlayersUl.children[childLen-1];
    // Iterate in reverse to keep the bounding boxes correct
    playerEntry.oldDomBox = playerEntry.getBoundingClientRect();

    let playerUUID = playerEntry.getAttribute("data-player-uuid");
    if (playerUUID) {
      existingNodes[playerUUID] = playerEntry;
      liElementContainer.appendChild(playerEntry); // Move to fragment
    } else {
      // Remove old items
      gameSidebarPlayersUl.removeChild(playerEntry);
    }
  }


  let playerUUIDsSorted = Object.keys(players);
  playerUUIDsSorted.sort((a, b) => (points[a] < points[b]) ? 1 : -1);

  // Add new elements
  for (let playerUUID of playerUUIDsSorted) {
    if (!players.hasOwnProperty(playerUUID)) continue;
    if (existingNodes.hasOwnProperty(playerUUID)) continue;
    let li = $("<li/>", {class: 'nav-item text-secondary', 'data-player-uuid': playerUUID});
    li.appendTo(liElementContainer);
    $("<a/>", {
      'href': '#', 'class': 'nav-link', 'text': ''
    }).appendTo(li);
    existingNodes[playerUUID] = li[0];
  }

  // Re-append names and update the text
  // Then animate motions
  for (let playerUUID of playerUUIDsSorted) {
    if (!players.hasOwnProperty(playerUUID)) continue;
    let text = players[playerUUID] +
      ' ' +
      (playerUUID in points ? ('[' + points[playerUUID] + ']') : '[-]')
      + (playerUUID === myUUID ? " (you) " : "");
    let li = existingNodes[playerUUID];
    li.children[0].innerHTML = text;

    gameSidebarPlayersUl.appendChild(li);

    // Animate
    (function (li, oldBox) {
      requestAnimationFrame(() => {
        let newBox = li.getBoundingClientRect();
        const deltaY = oldBox ? oldBox.top - newBox.top : window.innerHeight;
        if (deltaY) {
          // Prepare animation
          li.style.transform = `translate3d(0, ${deltaY}px, 0)`; // move back
          li.style.transition = "transform 0s"; // immediate transform

          if (deltaY < 0) { // Move down by resetting the transformation
            requestAnimationFrame(() => {
              li.style.transform = '';
              li.style.transition = 'transform 500ms';
            });
          } else {
            requestAnimationFrame(() => {
              li.style['text-shadow'] = "0px 0px 20px green";
              li.style.transform = '';
              li.style.transition = 'transform 500ms';
            });
            setTimeout(() => {
              li.style['text-shadow'] = '';
            }, 1000);
          }
        }
      })
    })(li, li.oldDomBox);
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
const qrModal = new bootstrap.Modal(document.getElementById('qrModal'), {
  close: 'true',
})

$("[data-action='new_song_suggestions']").on('click', function () {
  socket.send(JSON.stringify({'command': 'find_song_suggestions'}));
});

$("#new_song_watch").on('paste', function (e) {
  let paste = (e.originalEvent.clipboardData || window.clipboardData).getData('text');
  if (paste.startsWith("https")) {
    $("#new_song_watch").val(new URLSearchParams(new URL(paste).search).get('v'));
    e.preventDefault();
  }
});

$("#new_song_next").on('click', function () {
  const vid = document.getElementById('new_song_watch');
  socket.send(JSON.stringify({'command': 'init_download', 'id': vid.value}));
});

$("[data-song-report-button]").on('click', function () {
  $("[data-song-report-button]").attr("disabled", "disabled")
  if (currentGame.song_uuid)
    socket.send(JSON.stringify({
      'command': 'report_song',
      'uuid': currentGame.song_uuid,
      'votetype': $(this).attr("data-song-report-button"),
    }));
});

$("#setupNextButton").on('click', function () {
  if (!document.getElementById("setupPlayerArtist").value || !document.getElementById("setupPlayerTitle").value) {
    $(".click-once").removeAttr('disabled');
    alert("Please fill out the fields!");
    return;
  }
  socket.send(JSON.stringify({
    'command': 'init_fetch',
    'yt_id': addSongData.yt_id,
    'uuid': addSongData.uuid,
    'artist': document.getElementById("setupPlayerArtist").value,
    'title': document.getElementById("setupPlayerTitle").value
  }));
});

$("#setupAddButton").on('click', function () {

  if (!document.getElementById("setupPlayerArtist").value || !document.getElementById("setupPlayerTitle").value) {
    $(".click-once").removeAttr('disabled');
    alert("Please fill out the fields!");
    return;
  }

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
  socket.send(JSON.stringify(d));
});


$("#join_game_button").on('click', function () {
  const name = document.getElementById('user_name').value;
  window.localStorage.setItem('intro_user_name', name);
  socket.send(JSON.stringify({
    'command': 'join_game',
    'words': document.getElementById('join_game_words').value,
    'name': name
  }));
});

$('#new_game_mode_mc').change(function () {
  if ($(this).is(':checked')) {
    $('#new_game_keyboard_container').hide();
    $('#new_game_mc_container').show();
  }
});
$('#new_game_mode_input').change(function () {
  if ($(this).is(':checked')) {
    $('#new_game_keyboard_container').show();
    $('#new_game_mc_container').hide();
  }
});

$("#start_new_game_button").on('click', function () {
  let name = document.getElementById('user_name').value;
  window.localStorage.setItem('intro_user_name', name);
  socket.send(JSON.stringify({
    'command': 'start_game',
    'words': document.getElementById('join_game_words').value,
    'name': name,
    'song_tags': $("#newGameSettingsTags").val(),
    'input_mode': $("#new_game_mode_mc").is(':checked') ? 'mc' : 'input',
    'help_percentage': $("#newGameSettingsHelpPercentage").val(),
    'mc_chance_artist': $("#newGameSettingsMCArtistOnlyChance").val(),
    'mc_chance_title': $("#newGameSettingsMCTitleOnlyChance").val(),
    'presentation_mode': $('#new_game_presentation_mode_on').is(':checked'),
    'mute_players': $('#new_game_mute_mode_on').is(':checked'),
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
  if (currentGame && !dataSaveMode)
    loadIntoBuffer(currentGame.path, function () {
      guessNode = playSound(setupBuffer)
    });
});

$("#gameArtist").keyup(function (event) {
  if (event.keyCode === 13) {
    $("#gameTitle").focus();
  }
});
$("#gameTitle").keyup(function (event) {
  if (event.keyCode === 13) {
    $("#gameGuessButton").click();
  }
});

$("#gameGuessButton").on('click', function () {
  has_sent_guess = true;
  sendGuess(true);
  $(this).removeClass("btn-primary").addClass("btn-success")
});

$(".gameGuessButtonFixed").on('click', function () {
  $("#gameArtist").val($(this).data("artist"));
  $("#gameTitle").val($(this).data("title"));
  has_sent_guess = true;
  sendGuess(true);
  $(".gameGuessButtonFixed").removeClass("btn-info").addClass("btn-primary");
  $(this).removeClass("btn-primary").addClass("btn-info");
})

let has_sent_guess = false;

function sendGuess(announce) {
  let data = {
    artist: document.getElementById('gameArtist').value,
    title: document.getElementById('gameTitle').value,
  };
  if (has_sent_guess)
    data.has_sent_guess = true;
  if (announce)
    data.announce = true;
  socket.send(JSON.stringify({
    command: 'game_set_guess',
    guess: data,
  }))
}

// Copy the current invite link with the URL
$("#nav_room_code_btn").on('click', function () {
  let room_code = document.getElementById('nav_room_code').value;
  let copyText = document.querySelector("#nav_room_code");
  copyText.value = window.location.protocol + "//" + window.location.host + window.location.pathname + '?r=' + encodeURIComponent(room_code);
  copyText.select();
  document.execCommand("copy");
  copyText.value = room_code;
});

// Show the current invite URL as a QR code
$("#nav_room_code_qr_btn").on('click', function () {
  let room_code = document.getElementById('nav_room_code').value;
  let txt = window.location.protocol + "//" + window.location.host + window.location.pathname + '?r=' + encodeURIComponent(room_code);
  let elem = document.getElementById('qrModalBodyQR');
  elem.innerHTML = '';
  new QRCode(elem, {text: txt, width: 450, height: 450});
  qrModal.show();
});


$("#start_new_game_collapse_button").on('click', function () {
  socket.send(JSON.stringify({
    command: 'fetch_tags',
  }))
})

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

$(".click-once").on('click', function () {
  $(".click-once").attr('disabled', 'disabled');
})

$("[data-range-target]").on('change', function () {
  document.getElementById($(this).attr('data-range-target')).innerText = this.value;
});

$("#main-setup-suggestions_cards").on('click', '.suggestion-song-card-btn', function () {
  $("#new_song_watch").val($(this).attr('data-ytid'));
  $("#setupPlayerArtist").val($(this).attr('data-artist'));
  $("#setupPlayerTitle").val($(this).attr('data-title'));
  $("main").hide();
  $("#main-setup-1").show();
})

$("#btn_wifi_toggle").click(function () {
  if ($(this).val() === 'wifi') {
    $(this).removeClass("btn-primary").addClass("btn-secondary").text("data").val("data");
    showToast("Data friendly mode enabled", "No longer loading entire songs to play - ask someone else to play the songs for you!");
    dataSaveMode = true;
    $("#gamePlayButton").hide();
  } else {
    $(this).removeClass("btn-secondary").addClass("btn-primary").text("WiFi").val("wifi");
    showToast("Data friendly mode disabled", "Now playing the songs on your device - Watch your data usage :)")
    dataSaveMode = false;
    $("#gamePlayButton").show();
  }
});

function showToast(header, body, options) {
  let $toastDiv = $("<div/>", {class: 'toast hide', role: 'alert', 'aria-live': 'assertive', 'aria-atomic': 'true'});
  $toastDiv.appendTo($("#toastContainer"));
  let $headerDiv = $("<div/>", {class: 'toast-header'}).appendTo($toastDiv);
  $("<strong/>", {class: 'me-auto'}).text(header).appendTo($headerDiv);
  $("<button/>", {class: 'btn-close', 'data-bs-dismiss': 'toast', 'aria-label': 'Close'}).appendTo($headerDiv);
  $("<div/>", {class: 'toast-body'}).html(body).appendTo($toastDiv);
  let theToast = new bootstrap.Toast($toastDiv[0], options) // Returns a Bootstrap toast instance
  theToast.show();
  $toastDiv[0].addEventListener("hidden.bs.toast", function () {
    theToast.dispose();
    $toastDiv.remove();
  });
}

function showDebug() {
  showToast('Debug Menu', "<button class='btn btn-sm btn-danger' onclick='audioContext.close();_masterGain=undefined;audioContext=new AudioContext();'>Stop all audio</button>" +
    "&nbsp; <button class='btn btn-sm btn-danger' onclick='showAdmin(prompt())'>Admin</button>");
}