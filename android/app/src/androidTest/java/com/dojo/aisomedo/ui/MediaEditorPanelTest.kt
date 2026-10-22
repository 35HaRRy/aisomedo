package com.dojo.aisomedo.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.layout.boundsInRoot
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.dp
import com.dojo.aisomedo.api.*
import com.dojo.aisomedo.editor.*
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

class MediaEditorPanelTest {
    @get:Rule val compose = createComposeRule()
    private val writes = mutableListOf<List<String>>()
    private var editor by mutableStateOf(MediaEditorState().accept(snapshot()))
    private var busy by mutableStateOf(false)
    private var canMutate by mutableStateOf(true)
    private fun snapshot() = ActiveEditorOut(
        `package` = PackageOut("now", "active", 1, "active"), renderStale = true,
        contentRevision = 1, viewRevision = 1,
        media = listOf("a", "b", "c").map { id -> EditorMediaOut(
            artifacts = emptyList(), contentType = "video/mp4", effectiveDuration = 10.0,
            filename = "$id.mp4", isVideo = true, mediaId = id, previewUrl = null,
            processed = ProcessedMetadataOut(), sizeBytes = 10L, sourceDuration = 10.0, status = "finalized", uploadedAt = "now",
        ) }, montage = MontageOut(cardDuration = 0.0, clips = emptyList(), combinedDuration = 30.0,
            durationComplete = true, maxDurationSeconds = 90.0, order = listOf("a", "b", "c"),
            overLimit = false, requiredAction = null, selections = emptyMap(), trims = emptyMap()),
    )
    private fun show() {
        compose.setContent {
            val scroll = rememberScrollState()
            var viewport by remember { mutableStateOf(Rect.Zero) }
            DojoTheme {
                Column(Modifier.fillMaxSize().onGloballyPositioned { viewport = it.boundsInRoot() }
                    .verticalScroll(scroll).padding(16.dp)) {
                    MediaEditorPanel(editor, busy, scroll, viewport, {}, { writes.add(it) }, {}, {},
                        { id, rows -> editor = editor.edit(id, rows) }, {}, { editor = editor.discard() }, canMutate = canMutate)
                }
            }
        }
    }
    @Test fun dragHandleShowsInsertionAndCommitsOnlyOnDrop() {
        show()
        val handle = compose.onNodeWithTag("media-drag-a")
        val start = handle.fetchSemanticsNode().boundsInRoot.center
        val target = compose.onNodeWithTag("media-row-b").fetchSemanticsNode().boundsInRoot
        handle.performTouchInput {
            down(center)
            moveBy(Offset(0f, target.bottom - 8f - start.y), 300)
        }
        compose.onNodeWithTag("media-insertion-b-after").assertExists()
        compose.runOnIdle { assertTrue(writes.isEmpty()) }
        handle.performTouchInput { up() }
        compose.runOnIdle { assertEquals(listOf(listOf("b", "a", "c")), writes) }
    }
    @Test fun cancelledDragAndBlockedHandleNeverWrite() {
        show()
        compose.onNodeWithTag("media-drag-a").performTouchInput { down(center); moveBy(Offset(0f, 150f), 300); cancel() }
        compose.runOnIdle { assertTrue(writes.isEmpty()); busy = true }
        compose.onNodeWithTag("media-down-a").assertIsNotEnabled()
        compose.onNodeWithTag("media-remove-a").assertIsNotEnabled()
        compose.onNodeWithTag("media-drag-a").performTouchInput { swipeDown() }
        compose.runOnIdle { assertTrue(writes.isEmpty()) }
    }
    @Test fun accessibleMoveAndInvalidTrimFeedbackUseSameEditorState() {
        show()
        compose.onNodeWithTag("media-down-a").performClick()
        compose.runOnIdle { assertEquals(listOf(listOf("b", "a", "c")), writes) }
        compose.onNodeWithTag("media-edit-a").performClick()
        compose.onNodeWithTag("range-add-a").performScrollTo().performClick()
        compose.onNodeWithTag("range-start-a-0").performScrollTo().performTextReplacement("9")
        compose.onNodeWithTag("range-end-a-0").performTextReplacement("2")
        compose.onNodeWithTag("media-save").performScrollTo().assertIsNotEnabled()
        compose.onNodeWithTag("range-error-a").assertExists()
        compose.onNodeWithTag("range-end-a-0").performScrollTo().performTextReplacement("10")
        compose.onNodeWithTag("media-save").performScrollTo().assertIsEnabled()
        compose.onNodeWithTag("media-duration").assertTextContains("21.00", substring = true)
    }
    @Test fun offlineEditorCannotChangeOrderRangesOrDiscard() {
        editor = editor.edit("a", listOf(RangeInput("1", "3")))
        canMutate = false
        show()
        compose.onNodeWithTag("media-down-a").assertIsNotEnabled()
        compose.onNodeWithTag("media-remove-a").assertIsNotEnabled()
        compose.onNodeWithTag("media-save").assertIsNotEnabled()
        compose.onNodeWithText("Taslak değişikliklerden vazgeç").assertIsNotEnabled()
        compose.onNodeWithTag("media-edit-a").performScrollTo().performClick()
        compose.onNodeWithTag("range-start-a-0").assertIsNotEnabled()
        compose.onNodeWithTag("range-end-a-0").assertIsNotEnabled()
        compose.onNodeWithTag("media-drag-a").performScrollTo().performTouchInput { swipeDown() }
        compose.runOnIdle { assertTrue(writes.isEmpty()); assertTrue(editor.dirty) }
    }
    @Test fun recoveredDraftNeverEnablesFieldsBeforeSynchronization() {
        val draft = editor.edit("a", listOf(RangeInput("0", ""))).storedDraft!!
        editor = editor.restore(1, draft)
        canMutate = false
        show()
        compose.onNodeWithTag("media-save").assertIsNotEnabled()
        compose.onNodeWithTag("media-drag-a").assertIsNotEnabled()
        compose.onNodeWithTag("media-edit-a").performScrollTo().performClick()
        compose.onNodeWithTag("range-end-a-0").assertIsNotEnabled()
    }
    @Test fun storageFailureWarnsAndKeepsSaveDisabled() {
        editor = editor.edit("a", listOf(RangeInput("0", "5"))).copy(persistenceIssue = DraftIssue.STORAGE)
        show()
        compose.onNodeWithTag("draft-storage-warning").assertExists()
        compose.onNodeWithTag("media-save").assertIsNotEnabled()
        compose.onNodeWithTag("draft-storage-retry").assertIsEnabled()
    }
    @Test fun stationaryEdgeDragScrollsAndCancellationLeavesOrderUntouched() {
        val current = snapshot()
        val media = (1..12).map { index -> current.media.first().copy(mediaId = "item$index", filename = "item$index.mp4") }
        editor = MediaEditorState().accept(current.copy(media = media, montage = current.montage.copy(order = media.map { it.mediaId })))
        show()
        val handle = compose.onNodeWithTag("media-drag-item1")
        val start = handle.fetchSemanticsNode().boundsInRoot.center
        val screenBottom = compose.onRoot().fetchSemanticsNode().boundsInRoot.bottom
        handle.performTouchInput { down(center); moveBy(Offset(0f, screenBottom - 12f - start.y), 300) }
        val before = compose.onNodeWithTag("media-row-item1").fetchSemanticsNode().boundsInRoot.top
        compose.waitUntil(5000) { compose.onNodeWithTag("media-row-item1").fetchSemanticsNode().boundsInRoot.top < before }
        handle.performTouchInput { cancel() }
        compose.runOnIdle { assertTrue(writes.isEmpty()) }
    }
    @Test fun backCancelsDragBeforeFingerRelease() {
        show()
        val handle = compose.onNodeWithTag("media-drag-a")
        handle.performTouchInput { down(center); moveBy(Offset(0f, 150f), 300) }
        androidx.test.espresso.Espresso.pressBack()
        handle.performTouchInput { up() }
        compose.runOnIdle { assertTrue(writes.isEmpty()) }
    }
}
