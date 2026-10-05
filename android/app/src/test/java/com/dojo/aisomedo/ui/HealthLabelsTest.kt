package com.dojo.aisomedo.ui

import com.dojo.aisomedo.R
import org.junit.Assert.assertEquals
import org.junit.Test

class HealthLabelsTest {
    @Test fun backendRefreshReconnectAndOneoffStatesHaveSpecificLabels() {
        assertEquals(R.string.refresh_due, statusLabel("refresh_due"))
        assertEquals(R.string.reconnect_required, statusLabel("reconnect_required"))
        assertEquals(R.string.one_off, statusLabel("oneoff"))
        assertEquals(R.string.unknown_status, statusLabel("future-state"))
    }
}
