package com.dojo.aisomedo.ui

import androidx.compose.foundation.layout.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.dp
import com.dojo.aisomedo.api.UploadOut
import com.dojo.aisomedo.uploads.*
import org.junit.Rule
import org.junit.Test

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
    @Test fun conflictExplainsBlockWithoutOverwriteOrRetry() {
        show(UploadPhase.CONFLICT)
        compose.onNodeWithText("Dosya adı çakışıyor. Web uygulamasından çözün; otomatik üzerine yazılmaz.").assertExists()
        compose.onNodeWithText("Tekrar dene").assertDoesNotExist()
        compose.onNodeWithText("Duraklat").assertDoesNotExist()
    }
    @Test fun retryableOffersExplicitRetry() {
        show(UploadPhase.RETRYABLE)
        compose.onNodeWithText("Tekrar dene").assertExists()
    }
}
