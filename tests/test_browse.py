"""Folder browse helpers for curated/saved explore."""

from hexclack.music import browse


def test_parse_and_group_top_level() -> None:
    refs = browse.parse_folder_list(
        "Canon/Essentials\tA\nCanon/Warp\tB\nLanes/Work\tC\n\tRoot One\nNow/History\tReplay\n"
    )
    assert [r.top_level for r in refs] == ["Canon", "Canon", "Lanes", "Other", "Now"]
    groups = browse.group_by_top_level(refs)
    assert [(r.folder, r.name) for r in groups["Canon"]] == [
        ("Canon/Essentials", "A"),
        ("Canon/Warp", "B"),
    ]
    assert [(r.folder, r.name) for r in groups["Other"]] == [("", "Root One")]
    assert browse.category_order(groups)[0] == "Canon"


def test_group_keeps_same_name_in_different_folders() -> None:
    refs = browse.parse_folder_list("Canon/Essentials\tDup\nLanes/Work\tDup\n")
    groups = browse.group_by_top_level(refs)
    assert [(r.folder, r.name) for r in groups["Canon"]] == [("Canon/Essentials", "Dup")]
    assert [(r.folder, r.name) for r in groups["Lanes"]] == [("Lanes/Work", "Dup")]


def test_blacklist_folder_prefix_and_names() -> None:
    refs = browse.parse_folder_list("Demo/Darko\tHiFi\nLanes/Work\tFlow\nLanes/Club\tChill\nBot/Jazz\tDrop\n")
    kept = browse.filter_refs(refs, ["Demo", "Bot"], ["Chill"])
    assert [(r.folder, r.name) for r in kept] == [("Lanes/Work", "Flow")]


def test_blacklist_nested_history_folder() -> None:
    refs = browse.parse_folder_list("Now/History\tReplay\nNow/Fresh\tKeep\nLanes/Work\tFlow\n")
    kept = browse.filter_refs(refs, ["Now/History"], [])
    assert [(r.folder, r.name) for r in kept] == [("Now/Fresh", "Keep"), ("Lanes/Work", "Flow")]


def test_merge_blacklist_dedupes_defaults() -> None:
    assert browse.merge_blacklist(("Demo", "Bot"), ("Demo", "Extra")) == ("Demo", "Bot", "Extra")
