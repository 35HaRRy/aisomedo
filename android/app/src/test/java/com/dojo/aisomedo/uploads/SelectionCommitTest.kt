package com.dojo.aisomedo.uploads

import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class SelectionCommitTest {
    @Test fun accessLostAtCommitWaitsForRefreshInsteadOfDroppingSelection() = runTest {
        val access = MutableStateFlow(SelectionAvailability.READY)
        var attempts = 0
        val selection = async {
            awaitSelectionCommit(access) {
                attempts++
                if (attempts == 1) { access.value = SelectionAvailability.WAIT; false } else true
            }
        }
        runCurrent()
        assertFalse(selection.isCompleted)
        access.value = SelectionAvailability.READY
        assertTrue(selection.await())
        assertEquals(2, attempts)
    }

    @Test fun changedSessionOrNetworkInvalidatesWaitingSelection() = runTest {
        val access = MutableStateFlow(SelectionAvailability.WAIT)
        val selection = async { awaitSelectionCommit(access) { fail("Invalid selection must not commit"); true } }
        runCurrent()
        access.value = SelectionAvailability.INVALID
        assertFalse(selection.await())
    }

    @Test fun invalidationAtCommitCannotReplayAfterReconnect() = runTest {
        val access = MutableStateFlow(SelectionAvailability.READY)
        var attempts = 0
        assertFalse(awaitSelectionCommit(access) {
            attempts++
            access.value = SelectionAvailability.INVALID
            false
        })
        access.value = SelectionAvailability.READY
        runCurrent()
        assertEquals(1, attempts)
    }
}
