let setupPeaks;


(async function (Peaks) {
    // const audioContext = Tone.context;

    const playertest = {
        eventEmitter: null,
        playing: false,
        time: 0,
        sourceNode: null,
        startedAt: 0,
        pausedAt: 0,
        duration: 0,
        init: function (eventEmitter) {
            this.eventEmitter = eventEmitter;
            eventEmitter.emit('player.canplay');

        },
        destroy: function () {
            this.eventEmitter = null;
            this.sourceNode = null;
        },
        play: function () {
            if (this.isPlaying())
                this.pause();
            this.sourceNode = audioContext.createBufferSource();
            this.sourceNode.buffer = setupBuffer;
            this.sourceNode.connect(getMasterGain());
            this.duration = this.getDuration();
            this.sourceNode.start(0, this.pausedAt);
            this.startedAt = audioContext.currentTime - this.pausedAt;
            this.pausedAt = 0;
            this.playing = true;
            this.eventEmitter.emit('player.play', this.getCurrentTime());
            this.eventEmitter.emit('player.playing', this.getCurrentTime());
        },
        pause: function () {
            this.pausedAt = audioContext.currentTime - this.startedAt;
            this.startedAt = 0;
            if (this.sourceNode) {
                this.sourceNode.disconnect();
                this.sourceNode.stop(0);
                this.sourceNode = null;
            }
            this.playing = false;
            this.eventEmitter.emit('player.pause', this.getCurrentTime());
        },
        seek: function (time) {
            const wasPlaying = this.isPlaying();
            if (wasPlaying)
                this.pause();

            this.pausedAt = time;

            this.eventEmitter.emit('player.seeked', this.getCurrentTime());
            this.eventEmitter.emit('player.timeupdate', this.getCurrentTime());

            if (wasPlaying)
                this.play();
        },
        isPlaying: function () {
            return this.playing;
        },
        isSeeking: function () {
            return false;
        },
        getCurrentTime: function () {
            if (this.pausedAt)
                return this.pausedAt;
            return audioContext.currentTime - this.startedAt;
        },
        getDuration: function () {
            return setupBuffer.duration;
        },
    }

    setupPeaks = function (audioBuffer) {
        const options = {
            containers: {
                zoomview: document.getElementById('zoomview-container'),
                overview: document.getElementById('overview-container'),
            },
            player: playertest,
            webAudio: {
                audioBuffer: audioBuffer,
                scale: 128,
                multiChannel: false
            },
            keyboard: true,
            showPlayheadTime: true,
            zoomLevels: [128, 256, 512, 1024, 2048, 4096]
        };

        Peaks.init(options, function (err, peaksInstance) {
            if (err) {
                console.error(err.message);
                return;
            }

            console.log('Peaks instance ready');

            document.getElementById('setup_play').addEventListener('click', function () {
                peaksInstance.player.play();
            })
            document.getElementById('setup_pause').addEventListener('click', function () {
                peaksInstance.player.pause();
            })
            document.getElementById('setup_minus_2').addEventListener('click', function () {
                const seg = peaksInstance.segments.getSegment("peaks.segment.0");
                seg.update({startTime: Math.max(0, seg.startTime - 2), endTime: Math.max(0.5, seg.endTime - 2)});
            });
            document.getElementById('setup_plus_2').addEventListener('click', function () {
                const seg = peaksInstance.segments.getSegment("peaks.segment.0");
                seg.update({startTime: Math.min(18, seg.startTime + 2), endTime: Math.min(20, seg.endTime + 2)});
            });
            document.getElementById('setupPlayerTestButton').addEventListener('click', function () {
                peaksInstance.player.playSegment(peaksInstance.segments.getSegment("peaks.segment.0"))
            })
            peaksInstance.segments.add({
                startTime: 0.2,
                endTime: 1.5,
                labelText: "intro",
                editable: true
            });

            function updateSegmentTime(seg) {
                document.getElementById('setupPlayerTimeStart').value = Math.round(seg.startTime * 1000);
                document.getElementById('setupPlayerTimeEnd').value = Math.round(seg.endTime * 1000);
            }

            peaksInstance.on('segments.dragged', updateSegmentTime)
            updateSegmentTime(peaksInstance.segments.getSegment("peaks.segment.0"));

            const view = peaksInstance.views.getView('zoomview');
            view.enableAutoScroll(true);

        });
    }
})(peaks);

