package com.dojo.aisomedo.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.dp
import com.dojo.aisomedo.api.UploadOut
import com.dojo.aisomedo.uploads.*
import org.junit.Rule
import org.junit.Test
import org.junit.Assert.*
import kotlinx.serialization.json.*
import android.graphics.Bitmap
import com.dojo.aisomedo.api.ResolveConflictIn

class UploadPanelTest {
    @get:Rule val compose = createComposeRule()
    private fun row(phase: UploadPhase) = UploadRecord("00000000-0000-0000-0000-000000000033", "https://example.com", "a".repeat(64), "content://test/file", "Uzun dosya adı " .repeat(12) + ".mp4", "video/mp4", 1, 100,
        status = UploadOut(declaredSizeBytes = 100, receivedBytes = 100, receivedRanges = listOf(listOf(0, 100)), status = "processing", uploadId = "saved"),
        intent = if (phase == UploadPhase.PAUSED) UploadIntent.PAUSED else UploadIntent.ACTIVE, phase = phase)
    private fun show(phase: UploadPhase) = compose.setContent {
        DojoTheme { Column(Modifier.width(320.dp)) { UploadPanel(listOf(row(phase)), null, {}, {}, { _, _ -> }, { _, _ -> }, {}) } }
    }
    @Test fun pausedShowsResumeAndAccessibleProgress() {
        show(UploadPhase.PAUSED)
        compose.onNodeWithText("Devam et").assertExists()
        compose.onNodeWithText("Duraklat").assertDoesNotExist()
        compose.onNodeWithTag("upload-progress-${row(UploadPhase.PAUSED).id}").assert(SemanticsMatcher.keyIsDefined(SemanticsProperties.ProgressBarRangeInfo))
    }
    @Test fun processingIsNotFinalizedSuccess() {
        show(UploadPhase.PROCESSING)
        compose.onNodeWithText("Aktarım bitti; sunucuda işleniyor").assertExists()
        compose.onNodeWithText("Aktif Pakete eklendi").assertDoesNotExist()
    }
    @Test fun preparationDoesNotClaimUploadedPercentage() {
        show(UploadPhase.PREPARING)
        compose.onNodeWithText("Dosya doğrulanıyor; henüz aktarım değil").assertExists()
        compose.onNodeWithText("100 / 100 bayt · 100%").assertDoesNotExist()
    }
    @Test fun missingSourceAsksForOriginal() {
        show(UploadPhase.NEEDS_FILE)
        compose.onNodeWithText("Orijinal dosyayı seç").assertExists()
    }
    @Test fun conflictOffersAllDecisionsWithoutAutomaticOverwrite() {
        show(UploadPhase.CONFLICT)
        compose.onNodeWithText("İkisini de tut").assertExists()
        compose.onNodeWithText("Seçileni tut (hedefin üzerine yaz)").assertExists()
        compose.onNodeWithText("Hedefi tut (yüklemeyi atla)").assertExists()
        compose.onNodeWithText("Tekrar dene").assertDoesNotExist()
        compose.onNodeWithText("Duraklat").assertDoesNotExist()
    }
    @Test fun overwriteWaitsForPreviewAndConsentThenSendsExactTarget() {
        val target = buildJsonObject {
            put("media_id", "target"); put("filename", "İstanbul.jpg"); put("size_bytes", 10)
            put("uploaded_at", "2026-10-09T10:00:00Z")
            put("processed", buildJsonObject { put("content_type", "image/jpeg") })
        }
        val row = row(UploadPhase.CONFLICT).let { it.copy(status = it.status!!.copy(status = "conflict", conflicts = listOf(target))) }
        var sent: ResolveConflictIn? = null
        compose.setContent {
            DojoTheme { Column(Modifier.width(320.dp).verticalScroll(rememberScrollState())) {
                UploadPanel(listOf(row), null, {}, {}, { _, _ -> }, { _, _ -> }, {},
                    onResolve = { _, body -> sent = body }, onPreview = { _, _, file ->
                        val bitmap = Bitmap.createBitmap(8, 8, Bitmap.Config.ARGB_8888)
                        try { file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.JPEG, 90, it) } }
                        finally { bitmap.recycle() }
                    })
            } }
        }
        compose.onNodeWithText("Seçileni tut (hedefin üzerine yaz)").performScrollTo().performClick()
        compose.onNodeWithText("Hedefin üzerine yaz").assertIsNotEnabled()
        compose.onNodeWithText("Bu işlem geri alınamaz. Hedef dosya kalıcı olarak değiştirilecek.").assertExists()
        compose.waitUntil(5000) { compose.onAllNodesWithContentDescription("Hedef önizlemesi: İstanbul.jpg").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("Tüm uyumlu çakışmalara uygula").performScrollTo().performClick()
        compose.onNodeWithText("Kalıcı değişikliği onaylıyorum").performScrollTo().performClick()
        compose.onNodeWithText("Hedefin üzerine yaz").assertIsEnabled().performScrollTo().performClick()
        compose.runOnIdle {
            assertEquals("keep_selected", sent!!.decision)
            assertEquals("target", sent!!.targetMediaId)
            assertTrue(sent!!.confirmedOverwrite)
            assertTrue(sent!!.applyToAll)
        }
    }
    @Test fun failedPreviewBlocksOverwriteButNotKeepBoth() {
        show(UploadPhase.CONFLICT)
        compose.onNodeWithText("Seçileni tut (hedefin üzerine yaz)").assertIsNotEnabled()
        compose.onNodeWithText("Kararı uygula").assertIsEnabled()
    }
    @Test fun retryableOffersExplicitRetry() {
        show(UploadPhase.RETRYABLE)
        compose.onNodeWithText("Tekrar dene").assertExists()
    }
}
