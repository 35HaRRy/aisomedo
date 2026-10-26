package com.dojo.aisomedo.ui

import androidx.compose.runtime.*
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.semantics.SemanticsActions
import com.dojo.aisomedo.api.VideoRangeOut
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class MediaRangeTimelineTest {
    @get:Rule val compose = createComposeRule()
    @Test fun accessibleTerminalProgressKeepsExactNormalizedDuration() {
        val duration = 6.123456
        var captured = listOf(VideoRangeOut(start = 0.0, end = 5.0))
        compose.setContent {
            var ranges by remember { mutableStateOf(captured) }
            DojoTheme { MediaRangeTimeline(duration, ranges, false) { captured = it; ranges = it } }
        }
        compose.onAllNodes(SemanticsMatcher.keyIsDefined(SemanticsActions.SetProgress))[1].performSemanticsAction(SemanticsActions.SetProgress) { it(duration.toFloat()) }
        compose.runOnIdle { assertEquals(duration, captured.last().end, 0.0) }
    }
}
