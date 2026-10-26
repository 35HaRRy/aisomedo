from copy import deepcopy

import pytest
from dojo import MontageDurationExceeded, MontageTrimInvalid, PackageChanged, package_state
from dojo import exceptions as errors

from .test_selections import make_seam, video


def edit(key, base, proposed):
    return package_state.GroupEdit(key, base, proposed)


def apply(seam, store, revision, changes, package=None):
    package = package or seam.get_active_package()
    return seam.apply_package_edits(package.id, package.folder_name, revision, changes,
                                    requester="7")


def test_independent_video_edits_merge_without_replacing_untouched_values(tmp_path):
    store, seam = make_seam(tmp_path)
    a = video(tmp_path, seam, store, "a.mp4")
    b = video(tmp_path, seam, store, "b.mp4")
    revision = store.read_package_state(seam.get_active_package().id).content_revision
    apply(seam, store, revision, [edit(f"video:{a}", {"ranges": []},
                                     {"ranges": [{"start": 0, "end": 5}]})])
    result = apply(seam, store, revision, [edit(f"video:{b}", {"ranges": []},
                                              {"ranges": [{"start": 2, "end": 8}]})])
    assert result["montage"]["selections"] == {
        a: [{"start": 0, "end": 5}], b: [{"start": 2, "end": 8}],
    }


def test_same_video_range_endpoints_conflict_and_reject_whole_batch(tmp_path):
    store, seam = make_seam(tmp_path)
    a = video(tmp_path, seam, store, "a.mp4")
    b = video(tmp_path, seam, store, "b.mp4")
    seam.set_selections({a: [{"start": 0, "end": 10}]},
                        expected_folder_name=seam.get_active_package().folder_name)
    revision = store.read_package_state(seam.get_active_package().id).content_revision
    base = {"ranges": [{"start": 0, "end": 10}]}
    apply(seam, store, revision, [edit(f"video:{a}", base,
                                     {"ranges": [{"start": 1, "end": 10}]})])
    before = store.read_package_state(seam.get_active_package().id)
    with pytest.raises(errors.PackageEditConflict) as rejected:
        apply(seam, store, revision, [
            edit(f"video:{b}", {"ranges": []}, {"ranges": [{"start": 0, "end": 5}]}),
            edit(f"video:{a}", base, {"ranges": [{"start": 0, "end": 9}]}),
        ])
    assert [value["key"] for value in rejected.value.conflicts] == [f"video:{a}"]
    assert store.read_package_state(seam.get_active_package().id) == before


def test_identical_proposal_does_not_advance_revision_or_duplicate_audit(tmp_path):
    store, seam = make_seam(tmp_path)
    a = video(tmp_path, seam, store)
    revision = store.read_package_state(seam.get_active_package().id).content_revision
    change = edit(f"video:{a}", {"ranges": []}, {"ranges": [{"start": 0, "end": 5}]})
    first = apply(seam, store, revision, [change])
    audit_count = len(seam.list_audit())
    second = apply(seam, store, revision, [change])
    assert second["content_revision"] == first["content_revision"]
    assert len(seam.list_audit()) == audit_count


def test_merged_duration_limit_rejects_entire_batch(tmp_path):
    store, seam = make_seam(tmp_path)
    a = video(tmp_path, seam, store, "a.mp4")
    b = video(tmp_path, seam, store, "b.mp4")
    before = store.read_package_state(seam.get_active_package().id)
    store.set("montage.max_duration_seconds", 10, updated_at=seam._clock.now())
    with pytest.raises(MontageDurationExceeded):
        apply(seam, store, before.content_revision, [
            edit(f"video:{a}", {"ranges": []}, {"ranges": [{"start": 0, "end": 6}]}),
            edit(f"video:{b}", {"ranges": []}, {"ranges": [{"start": 0, "end": 6}]}),
        ])
    assert store.read_package_state(seam.get_active_package().id) == before


def test_removed_media_does_not_accept_old_edit(tmp_path):
    store, seam = make_seam(tmp_path)
    a = video(tmp_path, seam, store)
    revision = store.read_package_state(seam.get_active_package().id).content_revision
    seam.remove_media(a)
    before = store.read_package_state(seam.get_active_package().id)
    with pytest.raises(errors.PackageEditConflict):
        apply(seam, store, revision, [edit(f"video:{a}", {"ranges": []},
                                         {"ranges": [{"start": 0, "end": 5}]})])
    assert store.read_package_state(seam.get_active_package().id) == before


def test_package_identity_and_future_revision_are_rejected(tmp_path):
    store, seam = make_seam(tmp_path)
    package = seam.ensure_active_package()
    revision = store.read_package_state(package.id).content_revision
    change = edit("caption", {"text": None}, {"text": "new"})
    with pytest.raises(PackageChanged):
        seam.apply_package_edits(package.id + 1, package.folder_name, revision, [change])
    with pytest.raises(MontageTrimInvalid):
        apply(seam, store, revision + 100, [change])


@pytest.mark.parametrize("changes", [
    [("unknown", {}, {})],
    [("caption", {"text": None}, {"text": "x"}),
     ("caption", {"text": None}, {"text": "y"})],
    [("caption", {"text": None}, {"text": 42})],
    [("caption", {"text": None}, {"text": "x", "unexpected": True})],
    [("order", {"ids": []}, {"ids": ["unknown"]})],
    [("branding", {"settings": {}}, {"settings": {"secret": "x"}})],
])
def test_malformed_groups_do_not_mutate_input(changes):
    document = {"media": [], "order": [], "caption": None, "branding": {}}
    before = deepcopy(document)
    with pytest.raises(MontageTrimInvalid):
        package_state.merge_edit_groups(document, [edit(*value) for value in changes])
    assert document == before
