package com.dojo.aisomedo.editor

import com.dojo.aisomedo.api.*
import kotlinx.serialization.json.Json
import org.junit.Assert.*
import org.junit.Test

fun editorJson(folder: String = "active", order: String = "\"a\",\"b\",\"c\"", selections: String = "\"c\":[{\"start\":1,\"end\":3},{\"start\":7,\"end\":9}]", aStatus: String = "finalized", id: Int = 1): String = """{
    "package":{"id":$id,"folder_name":"$folder","created_at":"2026-10-10T12:00:00Z","status":"active"},
    "content_revision":1,"view_revision":1,"render_stale":true,"media":[
      {"media_id":"a","filename":"first.mp4","content_type":"video/mp4","size_bytes":2147483648,"uploaded_at":"now","status":"$aStatus","processed":{},"preview_url":null,"artifacts":[],"is_video":true,"source_duration":20,"effective_duration":20},
      {"media_id":"b","filename":"photo.jpg","content_type":"image/jpeg","size_bytes":3,"uploaded_at":"now","status":"finalized","processed":{},"preview_url":null,"artifacts":[],"is_video":false,"source_duration":null,"effective_duration":3},
      {"media_id":"c","filename":"last.mp4","content_type":"video/mp4","size_bytes":3,"uploaded_at":"now","status":"finalized","processed":{},"preview_url":null,"artifacts":[],"is_video":true,"source_duration":10,"effective_duration":4}
    ],"montage":{"order":[$order],"trims":{},"selections":{$selections},"clips":[],"combined_duration":32,"max_duration_seconds":90,"over_limit":false,"required_action":null,"card_duration":5,"duration_complete":true}
}"""

class MediaEditorTest {
    private val snapshot = Json.decodeFromString<ActiveEditorOut>(editorJson())
    @Test fun reopenRestoresReadOnlyAndIndependentChangesKeepOriginalBaseline() {
        val edited = MediaEditorState().accept(snapshot).edit("a", listOf(RangeInput("0", "")))
        val restored = MediaEditorState().restore(1, edited.storedDraft!!)
        assertTrue(restored.readRequired); assertFalse(restored.canSave)
        val fresh = snapshot.copy(montage = snapshot.montage.copy(selections = mapOf("c" to listOf(VideoRangeOut(start = 0.0, end = 2.0)))))
        val reconciled = restored.accept(fresh, explicit = true)
        assertEquals("", reconciled.inputs.getValue("a")[0].end)
        assertTrue(reconciled.conflicts.isEmpty())
        assertFalse(reconciled.readRequired)
    }

    @Test fun sameGroupNeedsExplicitChoiceAndLaterEditsCanConflictAgain() {
        val edited = MediaEditorState().accept(snapshot).edit("a", listOf(RangeInput("0", "5")))
        val fresh = snapshot.copy(contentRevision = 2, montage = snapshot.montage.copy(selections = snapshot.montage.selections + ("a" to listOf(VideoRangeOut(start = 2.0, end = 6.0)))))
        val conflict = edited.accept(fresh, explicit = true)
        assertFalse(conflict.canSave); assertTrue("video:a" in conflict.conflicts)
        val local = conflict.resolveConflict("video:a", local = true)
        assertTrue(local.canSave)
        assertEquals("5", local.inputs.getValue("a")[0].end)
        assertFalse(conflict.resolveConflict("video:a", local = false).dirty)
        assertTrue("video:a" in local.accept(snapshot).conflicts)
    }

    @Test fun uncertainWriteDoesNotReplay() {
        val edited = MediaEditorState().accept(snapshot).edit("a", listOf(RangeInput("0", "5")))
        val restored = MediaEditorState().restore(1, edited.storedDraft!!.copy(uncertain = true))
        assertFalse(restored.canSave)
        val committed = snapshot.copy(montage = snapshot.montage.copy(selections = snapshot.montage.selections + ("a" to listOf(VideoRangeOut(start = 0.0, end = 5.0)))))
        val recovered = restored.accept(committed, explicit = true)
        assertFalse(recovered.dirty); assertNull(recovered.storedDraft)
    }

    @Test fun completionKeepsDraftReadOnly() {
        val edited = MediaEditorState().accept(snapshot).edit("a", listOf(RangeInput("0", "5")))
        val completed = snapshot.copy(`package` = snapshot.`package`.copy(status = "completed"))
        val restored = MediaEditorState().restore(1, edited.storedDraft!!).accept(completed, explicit = true)
        assertFalse(restored.canSave); assertNotNull(restored.storedDraft)
        assertEquals("5", restored.inputs.getValue("a")[0].end)
    }
    @Test fun proposedDurationIncludesCardsPhotosAndAllSelectedSections() {
        val editor = MediaEditorState().accept(snapshot)
        assertEquals(32.0, editor.proposedTotal!!, 0.001)
        val changed = editor.edit("a", listOf(RangeInput("1,5", "4.5")))
        assertEquals(15.0, changed.proposedTotal!!, 0.001)
        assertEquals(listOf(VideoRangeOut(start = 1.5, end = 4.5)), changed.selections!!["a"])
        assertEquals(listOf(VideoRangeOut(start = 1.0, end = 3.0), VideoRangeOut(start = 7.0, end = 9.0)), changed.selections!!["c"])
    }
    @Test fun invalidPartialNonFiniteOverlappingAndShortRangesCannotSave() {
        val editor = MediaEditorState().accept(snapshot)
        listOf(
            listOf(RangeInput("", "3")), listOf(RangeInput("NaN", "3")),
            listOf(RangeInput("0", "Infinity")), listOf(RangeInput("-1", "3")),
            listOf(RangeInput("2", "1")), listOf(RangeInput("0", "21")),
            listOf(RangeInput("0", "0.01")), listOf(RangeInput("1", "4"), RangeInput("3", "5")),
        ).forEach { ranges ->
            val invalid = editor.edit("a", ranges)
            assertNull(invalid.selections); assertNull(invalid.proposedTotal)
            assertFalse(invalid.canSave)
            assertEquals(ranges, invalid.inputs["a"])
        }
        assertTrue(editor.edit("a", listOf(RangeInput("0", "0.04"))).canSave)
    }
    @Test fun resetRestoresWholeVideoAndSortsSelectionsWithoutChangingFieldRows() {
        val editor = MediaEditorState().accept(snapshot)
        val changed = editor.edit("c", listOf(RangeInput("7", "9"), RangeInput("1", "3")))
        assertEquals(listOf(VideoRangeOut(start = 1.0, end = 3.0), VideoRangeOut(start = 7.0, end = 9.0)), changed.selections!!["c"])
        assertEquals("7", changed.inputs["c"]!!.first().start)
        val reset = editor.edit("c", emptyList())
        assertFalse("c" in reset.selections!!)
        assertEquals(38.0, reset.proposedTotal!!, 0.001)
    }
    @Test fun refreshPreservesDirtyRangesButBlocksChangedPackageUntilDiscarded() {
        val draft = MediaEditorState().accept(snapshot).edit("a", listOf(RangeInput("2", "4")))
        val other = snapshot.copy(`package` = snapshot.`package`.copy(folderName = "new", id = 2))
        val refreshed = draft.accept(other, explicit = true)
        assertTrue(refreshed.readRequired); assertFalse(refreshed.canSave)
        assertEquals("2", refreshed.inputs["a"]!!.first().start)
        assertEquals("new", refreshed.discard().baseFolder)
        assertFalse(refreshed.discard().dirty)
        val concurrent = draft.accept(snapshot.copy(montage = snapshot.montage.copy(order = listOf("b", "a", "c"))))
        assertFalse(concurrent.readRequired)
        assertTrue(concurrent.accept(concurrent.snapshot!!, explicit = true).canSave)
    }
    @Test fun limitAndUnknownSourceBlockSavingWithoutInventingDuration() {
        val limited = snapshot.copy(montage = snapshot.montage.copy(maxDurationSeconds = 10.0))
        assertFalse(MediaEditorState().accept(limited).edit("a", listOf(RangeInput("0", "10"))).canSave)
        val unknown = snapshot.copy(media = snapshot.media.map { if (it.mediaId == "a") it.copy(sourceDuration = null) else it })
        assertNull(MediaEditorState().accept(unknown).proposedTotal)
    }
    @Test fun insertionBeforeAfterMovesExactlyOneItemAndIgnoresInvalidOrNoopDrop() {
        val order = listOf("a", "b", "c")
        assertEquals(listOf("b", "c", "a"), moveMedia(order, "a", "c", after = true))
        assertEquals(listOf("c", "a", "b"), moveMedia(order, "c", "a", after = false))
        assertEquals(order, moveMedia(order, "a", "b", after = false))
        assertEquals(order, moveMedia(order, "missing", "c", true))
        assertEquals(order, moveMedia(order, "b", "b", true))
    }
    @Test fun acknowledgedWriteCannotDiscardDraftIfReadBackIsAnotherPackageOrDifferentSelections() {
        val draft = MediaEditorState().accept(snapshot).edit("a", listOf(RangeInput("2", "4")))
        val expected = snapshot.copy(montage = snapshot.montage.copy(selections = draft.selections!!))
        val other = expected.copy(`package` = snapshot.`package`.copy(id = 2, folderName = "other"))
        val switched = draft.accept(other, explicit = true, expected = expected, savedTrims = true)
        assertTrue(switched.dirty); assertTrue(switched.readRequired)
        assertEquals("2", switched.inputs["a"]!!.first().start)
        val changed = expected.copy(montage = expected.montage.copy(selections = mapOf("a" to listOf(VideoRangeOut(start = 3.0, end = 5.0)))))
        val conflict = draft.accept(changed, explicit = true, expected = expected, savedTrims = true)
        assertTrue(conflict.dirty); assertTrue(conflict.readRequired)
        assertEquals("2", conflict.inputs["a"]!!.first().start)
    }
}
