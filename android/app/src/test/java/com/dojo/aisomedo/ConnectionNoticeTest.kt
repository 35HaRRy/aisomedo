package com.dojo.aisomedo

import com.dojo.aisomedo.live.LivePhase
import org.junit.Assert.*
import org.junit.Test

class ConnectionNoticeTest {
    @Test fun routineConnectionAndSyncStayQuietWithoutUnlockingWrites() {
        for (phase in listOf(LivePhase.CONNECTING, LivePhase.SYNCING)) {
            for (authoritative in listOf(false, true)) {
                val state = AppUiState(phase = Phase.READY, livePhase = phase, authoritative = authoritative)
                assertFalse("Routine $phase must not show a connection warning", state.showConnectionNotice)
                assertFalse(state.canMutate)
                assertFalse(state.copy(busy = true).showConnectionNotice)
            }
        }
    }

    @Test fun connectionAndSnapshotFailuresKeepWarningAndWriteProtection() {
        val live = AppUiState(phase = Phase.READY, livePhase = LivePhase.LIVE, authoritative = true)
        val failures = listOf(
            live.copy(networkConnected = false),
            live.copy(livePhase = LivePhase.DISCONNECTED),
            live.copy(livePhase = LivePhase.SYNCING, authoritative = false, issue = UiIssue.NETWORK),
            live.copy(livePhase = LivePhase.SYNCING, authoritative = false, issue = UiIssue.UNKNOWN),
        )
        for (state in failures) {
            assertTrue(state.showConnectionNotice)
            assertFalse(state.canMutate)
        }
        assertFalse(live.showConnectionNotice)
        assertTrue(live.canMutate)
        assertFalse(live.copy(issue = UiIssue.NETWORK).showConnectionNotice)
        assertFalse(live.copy(phase = Phase.PAIRING, networkConnected = false).showConnectionNotice)
    }
}
