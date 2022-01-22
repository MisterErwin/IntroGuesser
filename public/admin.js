$("tbody").on('click', '[data-admin-play-intro]', function () {
    loadIntoBuffer($(this).attr("data-admin-play-intro"), playSound);
})
    .on('click', '[data-admin-query-tag]', function () {
        let tagVal = $(this).attr("data-admin-query-tag");
        $("#song_list_table_tags")
            .append($("<span/>", {
                class: 'badge bg-primary mx1',
                'data-admin-query-tag': tagVal,
                text: tagVal,
            }));
        updateAdminSongList()
    });
$("#song_list_table_tags").on('click', '[data-admin-query-tag]', function () {
    $(this).remove();
    updateAdminSongList();
});

function updateAdminSongList() {
    let tags = [];
    for (let tag of $("#song_list_table_tags [data-admin-query-tag]")) {
        console.log(tag);
        tags.push($(tag).attr('data-admin-query-tag'));
    }
    if (tags.length === 0) {
        $("[data-song-uuid]").show();
        return;
    }
    for (let uuid in adminSongs) {
        let show = false;
        if (adminSongs[uuid].tags) {
            for (let tag of adminSongs[uuid].tags)
                if (tags.includes(tag.tag)) {
                    show = true;
                    break;
                }
        }
        if (show)
            $("[data-song-uuid='" + uuid + "']").show();
        else
            $("[data-song-uuid='" + uuid + "']").hide();
    }
}

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
