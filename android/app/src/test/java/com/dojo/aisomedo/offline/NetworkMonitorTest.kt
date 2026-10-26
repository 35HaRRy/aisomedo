package com.dojo.aisomedo.offline

import org.junit.Assert.*
import org.junit.Test

class NetworkMonitorTest {
    @Test fun handoverIgnoresObsoleteLoss() {
        val tracker = NetworkTracker()
        tracker.available("A"); tracker.capabilities("A", true, true)
        tracker.available("B"); assertFalse(tracker.state.value.connected)
        tracker.capabilities("B", true, true)
        val epoch = tracker.state.value.epoch
        tracker.lost("A"); tracker.capabilities("A", false, false)
        assertTrue(tracker.state.value.connected)
        assertEquals(epoch, tracker.state.value.epoch)
    }
    @Test fun availableAloneCannotEnableNetwork() {
        val tracker = NetworkTracker()
        tracker.available("A"); assertFalse(tracker.state.value.connected)
        tracker.capabilities("A", true, false); assertFalse(tracker.state.value.connected)
        tracker.capabilities("A", false, true); assertFalse(tracker.state.value.connected)
    }
    @Test fun lossAndRevalidationAdvanceEpoch() {
        val tracker = NetworkTracker()
        tracker.available("A"); tracker.capabilities("A", true, true)
        val epoch = tracker.state.value.epoch
        tracker.capabilities("A", true, true); assertEquals(epoch, tracker.state.value.epoch)
        tracker.lost("A"); assertFalse(tracker.state.value.connected)
        tracker.available("B"); tracker.capabilities("B", true, true)
        assertTrue(tracker.state.value.connected); assertTrue(tracker.state.value.epoch > epoch)
    }
    @Test fun initialSnapshotCannotOverwriteNewerCallback() {
        val tracker = NetworkTracker()
        tracker.available("B"); tracker.capabilities("B", true, true)
        tracker.initialize("A", false, false)
        assertTrue(tracker.state.value.connected)
    }
    @Test fun initialLossRejectsObsoleteValidatedSample() {
        val tracker = NetworkTracker()
        tracker.lost("A")
        tracker.initialize("A", true, true)
        assertFalse(tracker.state.value.connected)
        tracker.available("B"); tracker.capabilities("B", true, true)
        assertTrue(tracker.state.value.connected)
    }
}
