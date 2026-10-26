package com.dojo.aisomedo.ui

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import com.dojo.aisomedo.api.*
import com.dojo.aisomedo.editor.MediaEditorState
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class SavedReelPanelTest {
    @get:Rule val compose = createComposeRule()

    @Test fun invalidatedReelShowsNotRenderedWithoutRenderingOrDownloading() {
        var renders = 0
        var downloads = 0
        val snapshot = ActiveEditorOut(
            `package` = PackageOut("now", "active", 1, "active"),
            contentRevision = 2, viewRevision = 2,
            renderStale = true, renderStatus = "stale", media = emptyList(),
            montage = MontageOut(cardDuration = 0.0, clips = emptyList(), combinedDuration = 3.0,
                durationComplete = true, maxDurationSeconds = 90.0, order = listOf("photo"),
                overLimit = false, requiredAction = null, selections = emptyMap(), trims = emptyMap()),
        )
        compose.setContent {
            DojoTheme {
                SavedReelPanel(MediaEditorState().accept(snapshot), true, { renders++ }, { _, _ -> downloads++ })
            }
        }
        compose.onNodeWithText("Kaydedilmiş montajı henüz render edilmedi.").assertIsDisplayed()
        compose.runOnIdle {
            assertEquals(0, renders)
            assertEquals(0, downloads)
        }
    }
}
