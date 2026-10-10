package com.dojo.aisomedo.ui

import android.graphics.Bitmap
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.dp
import com.dojo.aisomedo.api.UploadOut
import com.dojo.aisomedo.uploads.*
import kotlinx.coroutines.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import java.io.File
import java.util.concurrent.atomic.AtomicInteger

class ConflictPreviewTest {
    @get:Rule val compose = createComposeRule()
    private fun row(): UploadRecord {
        val target = buildJsonObject {
            put("media_id", "target"); put("filename", "İstanbul.jpg"); put("size_bytes", 10)
            put("uploaded_at", "2026-10-09T10:00:00Z")
            put("processed", buildJsonObject { put("content_type", "image/jpeg") })
        }
        return UploadRecord("00000000-0000-0000-0000-000000000034", "https://example.com", "a".repeat(64), "content://test/file", "İstanbul.jpg", "image/jpeg", 1, 10,
            status = UploadOut(declaredSizeBytes = 10, receivedBytes = 0, receivedRanges = emptyList(), status = "conflict", uploadId = "saved", conflicts = listOf(target)), phase = UploadPhase.CONFLICT)
    }
    private fun jpeg(file: File) {
        val bitmap = Bitmap.createBitmap(8, 8, Bitmap.Config.ARGB_8888)
        try { file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.JPEG, 90, it) } }
        finally { bitmap.recycle() }
    }
    @Test fun revisionFenceCancellationShowsRetryAndDeletesPreview() {
        val calls = AtomicInteger()
        var failedFile: File? = null
        compose.setContent {
            DojoTheme { Column(Modifier.width(320.dp).verticalScroll(rememberScrollState())) {
                UploadPanel(listOf(row()), null, {}, {}, { _, _ -> }, { _, _ -> }, {}, onPreview = { _, _, file ->
                    if (calls.incrementAndGet() == 1) { failedFile = file; throw CancellationException("Upload action changed") }
                    jpeg(file)
                })
            } }
        }
        compose.waitUntil(5000) { compose.onAllNodesWithText("Tekrar dene").fetchSemanticsNodes().isNotEmpty() }
        compose.runOnIdle { assertFalse(failedFile!!.exists()) }
        compose.onNodeWithText("Tekrar dene").performScrollTo().performClick()
        compose.waitUntil(5000) { compose.onAllNodesWithContentDescription("Hedef önizlemesi: İstanbul.jpg").fetchSemanticsNodes().isNotEmpty() }
    }
    @Test fun refreshCompletesBeforeReplacementPreviewLoads() {
        val calls = AtomicInteger()
        val release = CompletableDeferred<Unit>()
        compose.setContent {
            var current by remember { mutableStateOf(row()) }
            DojoTheme { Column(Modifier.width(320.dp).verticalScroll(rememberScrollState())) {
                UploadPanel(listOf(current), null, {}, {}, { _, _ -> }, { _, _ -> }, {},
                    onRefresh = { release.await(); current = current.copy(revision = current.revision + 1) },
                    onPreview = { _, _, file -> calls.incrementAndGet(); jpeg(file) })
            } }
        }
        compose.waitUntil(5000) { calls.get() == 1 && compose.onAllNodesWithContentDescription("Hedef önizlemesi: İstanbul.jpg").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("Yenile").performScrollTo().performClick()
        compose.runOnIdle { assertEquals(1, calls.get()); release.complete(Unit) }
        compose.waitUntil(5000) { calls.get() == 2 && compose.onAllNodesWithContentDescription("Hedef önizlemesi: İstanbul.jpg").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("Seçileni tut (hedefin üzerine yaz)").performScrollTo().performClick()
        compose.onNodeWithText("Kalıcı değişikliği onaylıyorum").assertIsEnabled()
    }
    @Test fun undecodableVideoReleasesPrivateFileAndBlocksOverwrite() {
        var file: File? = null
        val original = row()
        val target = original.status!!.conflicts.single() + ("processed" to buildJsonObject { put("content_type", "video/mp4") })
        val video = original.copy(status = original.status.copy(conflicts = listOf(target)))
        compose.setContent {
            DojoTheme { Column(Modifier.width(320.dp).verticalScroll(rememberScrollState())) {
                UploadPanel(listOf(video), null, {}, {}, { _, _ -> }, { _, _ -> }, {}, onPreview = { _, _, preview ->
                    file = preview; preview.writeText("not an MP4")
                })
            } }
        }
        compose.waitUntil(10000) { compose.onAllNodesWithText("Tekrar dene").fetchSemanticsNodes().isNotEmpty() }
        compose.runOnIdle { assertFalse(file!!.exists()) }
        compose.onNodeWithText("Seçileni tut (hedefin üzerine yaz)").performScrollTo().performClick()
        compose.onNodeWithText("Hedefin üzerine yaz").assertIsNotEnabled()
    }
}
