package com.dojo.aisomedo.reviews

import androidx.compose.foundation.layout.Column
import androidx.compose.runtime.*
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import com.dojo.aisomedo.ui.*
import com.dojo.aisomedo.uploads.*
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

class ReviewContinuationTest {
    @get:Rule val compose = createComposeRule()
    @Test fun bannerKeepsUploadControlsVisibleAndOnlyExplicitContinueCallsRenderCallback() {
        var requests = 0
        compose.setContent { DojoTheme { Column {
            ReviewContinuation(ReviewState(target = ReviewTarget(occurrenceId = 2, packageFolder = "active", action = ReviewAction.UPLOAD)), true,
                emptyList(), { _, _ -> requests++ }, {}, {}, {})
            UploadPanel(emptyList(), null, {}, {}, { _, _ -> }, { _, _ -> }, {})
        } } }
        compose.onNodeWithText("Fotoğraf / video seç").assertExists()
        assertEquals(0, requests)
        compose.onNodeWithTag("review-continue").performClick()
        assertEquals(1, requests)
    }
}
