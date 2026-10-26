package com.dojo.aisomedo.ui

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import com.dojo.aisomedo.api.*
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class MediaFullscreenDialogTest {
    @get:Rule val compose = createComposeRule()
    @Test fun unsupportedOriginalNeverDownloadsProcessedFallback() {
        val requests = mutableListOf<String>()
        val media = EditorMediaOut(artifacts = emptyList(), contentType = "video/quicktime", effectiveDuration = 6.0,
            filename = "source.mov", isVideo = true, mediaId = "a", previewUrl = "/processed.mp4", originalUrl = "/original.mov",
            processed = ProcessedMetadataOut(), sizeBytes = 10, sourceDuration = 6.0, status = "finalized", uploadedAt = "now")
        compose.setContent { DojoTheme { MediaFullscreenDialog(media, {}) { path, _ -> requests.add(path); error("Unsupported original") } } }
        compose.onNodeWithText("Medya önizlemesi yüklenemedi. Yeniden deneyin.").assertExists()
        compose.runOnIdle { assertEquals(listOf("/original.mov"), requests) }
        compose.onNodeWithContentDescription("Tam ekranı kapat").assertExists()
    }
}
