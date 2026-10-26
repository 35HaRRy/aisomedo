package com.dojo.aisomedo.ui

import org.junit.Assert.*
import org.junit.Test

class MediaTimelineBoundsTest {
    @Test fun terminalFloatValuesKeepExactDoubleBoundsAfterRounding() {
        for (duration in listOf(6.123456, 6.1238)) {
            assertEquals(duration, timelineBound(duration.toFloat(), 0.04, duration), 0.0)
            assertEquals(0.0, timelineBound(0f, 0.0, duration - 0.04), 0.0)
            assertTrue(timelineBound((duration - 0.0001).toFloat(), 0.04, duration) <= duration)
            assertEquals(duration - 0.04, timelineBound(100f, 0.0, duration - 0.04), 0.0)
        }
    }
}
