package com.dojo.aisomedo.live

import com.dojo.aisomedo.api.ApiFailure
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.test.*
import org.junit.Assert.*
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class LiveCoordinatorTest {
    @Test fun heartbeatsDoNotPoll() = runTest {
        val events = MutableSharedFlow<LiveEvent>()
        var reads = 0
        val live = LiveCoordinator(backgroundScope, { events }, { reads++ })
        live.setForeground(true); runCurrent()
        events.emit(LiveEvent("ready", protocol = 1)); runCurrent()
        assertEquals(LivePhase.LIVE, live.phase.value)
        repeat(40) {
            advanceTimeBy(15_000); events.emit(LiveEvent("heartbeat")); runCurrent()
        }
        assertEquals(1, reads)
        live.stop()
    }

    @Test fun disconnectLocksUntilResync() = runTest {
        val events = MutableSharedFlow<LiveEvent>()
        var read = CompletableDeferred<Unit>()
        val live = LiveCoordinator(backgroundScope, { events }, { read.await() })
        live.setForeground(true); runCurrent()
        events.emit(LiveEvent("ready", protocol = 1)); runCurrent()
        assertEquals(LivePhase.SYNCING, live.phase.value)
        read.complete(Unit); runCurrent()
        assertEquals(LivePhase.LIVE, live.phase.value)
        advanceTimeBy(45_000); runCurrent()
        assertEquals(LivePhase.DISCONNECTED, live.phase.value)
        read = CompletableDeferred()
        advanceTimeBy(31_000); runCurrent()
        events.emit(LiveEvent("ready", protocol = 1)); runCurrent()
        assertEquals(LivePhase.SYNCING, live.phase.value)
        read.complete(Unit); runCurrent()
        assertEquals(LivePhase.LIVE, live.phase.value)
        live.stop()
    }

    @Test fun invalidationDuringReadIsNotLost() = runTest {
        val events = MutableSharedFlow<LiveEvent>()
        val release = CompletableDeferred<Unit>()
        var reads = 0; var active = 0; var maximum = 0
        val live = LiveCoordinator(backgroundScope, { events }, {
            reads++; active++; maximum = maxOf(maximum, active)
            if (reads == 1) release.await()
            active--
        })
        live.setForeground(true); runCurrent()
        events.emit(LiveEvent("ready", protocol = 1)); runCurrent()
        events.emit(LiveEvent("change", eventId = "one", versions = mapOf("package:1" to 1))); runCurrent()
        events.emit(LiveEvent("change", eventId = "two", versions = mapOf("package:1" to 2))); runCurrent()
        release.complete(Unit); runCurrent()
        assertEquals(2, reads); assertEquals(1, maximum)
        assertEquals(LivePhase.LIVE, live.phase.value)
        events.emit(LiveEvent("change", eventId = "duplicate", versions = mapOf("package:1" to 2))); runCurrent()
        assertEquals(2, reads)
        live.setForeground(false); runCurrent()
        assertEquals(LivePhase.DISCONNECTED, live.phase.value)
        live.stop()
    }

    @Test fun unauthorizedStreamStopsReconnect() = runTest {
        var connections = 0
        val live = LiveCoordinator(backgroundScope, { flow { connections++; throw ApiFailure(401) } }, {})
        live.setForeground(true); runCurrent()
        assertEquals(LivePhase.UNAUTHORIZED, live.phase.value)
        advanceTimeBy(600_000); runCurrent()
        assertEquals(1, connections)
        live.stop()
    }

    @Test fun failedSnapshotStaysLockedWithoutPeriodicReadRetry() = runTest {
        val events = MutableSharedFlow<LiveEvent>()
        var reads = 0
        val live = LiveCoordinator(backgroundScope, { events }, { reads++; throw ApiFailure(0) })
        live.setForeground(true); runCurrent()
        events.emit(LiveEvent("ready", protocol = 1)); runCurrent()
        repeat(40) { advanceTimeBy(15_000); events.emit(LiveEvent("heartbeat")); runCurrent() }
        assertEquals(LivePhase.SYNCING, live.phase.value); assertEquals(1, reads)
        live.invalidate(setOf("dashboard")); runCurrent()
        assertEquals(2, reads)
        live.stop()
    }

    @Test fun unrelatedInvalidationCannotUnlockAfterInitialSyncFails() = runTest {
        val events = MutableSharedFlow<LiveEvent>()
        var fail = true
        val requested = mutableListOf<Set<String>>()
        val live = LiveCoordinator(backgroundScope, { events }, { resources ->
            requested += resources
            if (fail) throw ApiFailure(0)
        })
        live.setForeground(true); runCurrent()
        events.emit(LiveEvent("ready", protocol = 1)); runCurrent()
        assertEquals(LivePhase.SYNCING, live.phase.value)
        fail = false
        live.invalidate(setOf("settings")); runCurrent()
        assertTrue(requested.last().contains("*"))
        assertEquals(LivePhase.LIVE, live.phase.value)
        live.stop()
    }

    @Test fun invalidationDuringFailedReadStillGetsOneFollowup() = runTest {
        val events = MutableSharedFlow<LiveEvent>()
        val release = CompletableDeferred<Unit>()
        var reads = 0
        val live = LiveCoordinator(backgroundScope, { events }, {
            reads++
            if (reads == 1) { release.await(); throw ApiFailure(0) }
        })
        live.setForeground(true); runCurrent()
        events.emit(LiveEvent("ready", protocol = 1)); runCurrent()
        events.emit(LiveEvent("change", eventId = "one", versions = mapOf("dashboard" to 1))); runCurrent()
        release.complete(Unit); runCurrent()
        assertEquals(2, reads); assertEquals(LivePhase.LIVE, live.phase.value)
        live.stop()
    }
}
