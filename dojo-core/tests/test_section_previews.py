from copy import deepcopy

import pytest
from dojo import MontageDurationExceeded, PackageChanged
from dojo.package_state import GroupEdit

from .test_selections import finalize_media, make_seam, video


def state(store, seam):
    return store.read_package_state(seam.get_active_package().id)


def preview_jobs(store, seam):
    return [j for j in store.package_work(seam.get_active_package())[1]
            if j.kind == "section_preview"]


def save_sections(seam, mid, ranges):
    snapshot = seam.get_active_editor()
    return seam.apply_package_edits(
        snapshot["package"]["id"], snapshot["package"]["folder_name"],
        snapshot["content_revision"], [GroupEdit(f"video:{mid}",
            {"ranges": snapshot["montage"]["selections"].get(mid, [])}, {"ranges": ranges})],
    )


@pytest.mark.parametrize("writer", ["groups", "selections", "trims"])
def test_every_selection_write_queues_one_saved_generation(tmp_path, writer):
    store, seam = make_seam(tmp_path)
    mid = video(tmp_path, seam, store)
    package = seam.get_active_package()
    before = state(store, seam)
    ranges = [{"start": 2.0, "end": 5.0}]
    if writer == "groups":
        save_sections(seam, mid, ranges)
    elif writer == "selections":
        seam.set_selections({mid: ranges}, expected_folder_name=package.folder_name)
    else:
        seam.set_trims({mid: ranges[0]}, expected_folder_name=package.folder_name)
    after = state(store, seam)
    record = after.document["section_previews"][mid]
    (job,) = preview_jobs(store, seam)
    assert record["generation"] == job.job_id
    assert record["status"] == "queued" and record["artifact_ref"] is None
    assert job.payload["ranges"] == [{"start": 2.0, "end": 5.0}]
    assert job.payload["package_id"] == package.id
    assert job.payload["media_id"] == mid
    assert after.content_revision == before.content_revision + 1
    save_sections(seam, mid, ranges)
    assert len(preview_jobs(store, seam)) == 1
    assert state(store, seam) == after


def test_new_selection_cancels_only_its_video_and_empty_means_whole_source(tmp_path):
    store, seam = make_seam(tmp_path)
    a = video(tmp_path, seam, store, "a.mp4")
    b = video(tmp_path, seam, store, "b.mp4")
    save_sections(seam, a, [{"start": 0, "end": 5}])
    first_a = state(store, seam).document["section_previews"][a]["generation"]
    save_sections(seam, b, [{"start": 2, "end": 6}])
    first_b = state(store, seam).document["section_previews"][b]["generation"]
    save_sections(seam, a, [{"start": 10, "end": 15}])
    assert store.get(first_a).status == "cancelled"
    assert store.get(first_b).status == "queued"
    latest_a = state(store, seam).document["section_previews"][a]["generation"]
    save_sections(seam, a, [])
    assert store.get(latest_a).status == "cancelled"
    assert a not in state(store, seam).document["section_previews"]
    assert seam.get_montage_status().combined_duration == 34.0


def test_other_edits_and_derived_progress_preserve_generation_and_content_identity(tmp_path):
    store, seam = make_seam(tmp_path)
    mid = video(tmp_path, seam, store)
    photo = finalize_media(tmp_path, seam, store)
    save_sections(seam, mid, [{"start": 0, "end": 5}])
    generation = state(store, seam).document["section_previews"][mid]["generation"]
    seam.set_order([photo, mid])
    current = state(store, seam)
    seam.apply_package_edits(current.package_id, seam.get_active_package().folder_name,
                            current.content_revision, [GroupEdit(f"photo:{photo}",
                                {"seconds": 3.0}, {"seconds": 4.0})])
    before = state(store, seam)
    digest = seam._render_digest(seam.get_active_package(), before.document)
    document = deepcopy(before.document)
    document["section_previews"][mid]["status"] = "processing"
    seam._write_manifest(seam.get_active_package(), document)
    after = state(store, seam)
    assert after.document["section_previews"][mid]["generation"] == generation
    assert len(preview_jobs(store, seam)) == 1
    assert after.content_revision == before.content_revision
    assert after.view_revision > before.view_revision
    assert seam._render_digest(seam.get_active_package(), after.document) == digest


def test_removal_cancels_and_restore_requests_saved_sections(tmp_path):
    store, seam = make_seam(tmp_path)
    mid = video(tmp_path, seam, store)
    save_sections(seam, mid, [{"start": 0, "end": 5}])
    old = state(store, seam).document["section_previews"][mid]["generation"]
    seam.remove_media(mid)
    assert store.get(old).status == "cancelled"
    assert mid not in state(store, seam).document["section_previews"]
    seam.restore_media(mid)
    restored = state(store, seam).document["section_previews"][mid]
    assert restored["generation"] != old
    assert seam.get_montage_status().selections[mid] == [{"start": 0.0, "end": 5.0}]


def test_rejected_selection_does_not_create_jobs(tmp_path):
    store, seam = make_seam(tmp_path)
    mid = video(tmp_path, seam, store)
    before = state(store, seam)
    store.set("montage.max_duration_seconds", 1, updated_at=seam._clock.now())
    with pytest.raises(MontageDurationExceeded):
        save_sections(seam, mid, [{"start": 0, "end": 5}])
    assert state(store, seam) == before
    assert preview_jobs(store, seam) == []


def test_enqueue_failure_rolls_back_edit_and_invalidation(tmp_path, monkeypatch):
    store, seam = make_seam(tmp_path)
    mid = video(tmp_path, seam, store)
    before = state(store, seam)

    def reject(*args, **kwargs):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(store, "create_job_once", reject)
    with pytest.raises(RuntimeError, match="queue unavailable"):
        save_sections(seam, mid, [{"start": 0, "end": 5}])
    assert state(store, seam) == before
    assert preview_jobs(store, seam) == []


def test_retry_is_saved_generation_bound_and_duplicate_safe(tmp_path):
    store, seam = make_seam(tmp_path)
    mid = video(tmp_path, seam, store)
    save_sections(seam, mid, [{"start": 0, "end": 5}])
    failed = seam.claim_next_job()
    store.finish_if_processing(failed.job_id, status="failed", finished_at=seam._clock.now())
    document = state(store, seam).document
    document["section_previews"][mid]["status"] = "failed"
    seam._write_manifest(seam.get_active_package(), document)
    package = seam.get_active_package()
    args = dict(expected_package_id=package.id, expected_folder_name=package.folder_name,
                expected_generation=failed.job_id)
    seam.retry_section_preview(mid, **args)
    current = state(store, seam).document["section_previews"][mid]
    assert current["generation"] != failed.job_id
    assert current["retry_of"] == failed.job_id
    seam.retry_section_preview(mid, **args)
    assert state(store, seam).document["section_previews"][mid] == current
    save_sections(seam, mid, [{"start": 10, "end": 15}])
    before = state(store, seam)
    with pytest.raises(PackageChanged):
        seam.retry_section_preview(mid, **args)
    assert state(store, seam) == before
