package com.dojo.aisomedo.uploads

import android.app.NotificationManager
import android.os.Build
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

/** These checks require a dedicated, unlocked API 33 or API 34+ test emulator. */
class BackgroundUploadTest {
    @Test fun backgroundAndScreenOffContinueTransfer() {
        UploadDeviceFixture().use { f ->
            f.delayMillis = 750
            f.select(f.document(CHUNK_BYTES * 8, unknown = true))
            f.await { f.offsets.isNotEmpty() }
            val before = f.uploads.values.sumOf { it.received }
            f.shell("input keyevent KEYCODE_HOME")
            f.await { f.uploads.values.sumOf { it.received } > before }
            val background = f.uploads.values.sumOf { it.received }
            f.shell("input keyevent KEYCODE_SLEEP")
            try {
                f.await { f.uploads.values.sumOf { it.received } > background }
                assertTrue(f.uploads.values.sumOf { it.received } > background)
            } finally { f.shell("input keyevent KEYCODE_WAKEUP"); f.shell("wm dismiss-keyguard") }
            f.await { f.runtime.rows.value.singleOrNull()?.phase == UploadPhase.QUEUED }
            assertEquals(1, f.initializationCount.get())
        }
    }
    @Test fun disconnectAndSystemStopResumeKnownId() {
        UploadDeviceFixture().use { f ->
            f.losePut = true
            f.select(f.document(CHUNK_BYTES * 3))
            f.await { f.offsets.isNotEmpty() && f.runtime.rows.value.singleOrNull()?.status != null }
            val row = f.runtime.rows.value.single()
            val id = row.status!!.uploadId
            if (Build.VERSION.SDK_INT >= 34) f.shell("cmd jobscheduler timeout -n dojo-uploads ${f.target.packageName} 3300")
            else f.shell("cmd jobscheduler timeout ${f.target.packageName}")
            // Stop is not pause. Explicit visible resume wakes the platform without replacing server ID.
            assertEquals(UploadIntent.ACTIVE, f.runtime.rows.value.single().intent)
            f.front()
            f.runtime.retry(row.id)
            f.await { f.runtime.rows.value.singleOrNull()?.phase == UploadPhase.QUEUED }
            assertEquals(id, f.runtime.rows.value.single().status!!.uploadId)
            assertEquals(listOf(0L, 2097152L, 4194304L), f.offsets.filter { it.first == id }.map { it.second })
            assertEquals(1, f.initializationCount.get())
        }
    }
    @Test fun notificationPauseStaysPausedAfterReopen() {
        UploadDeviceFixture().use { f ->
            f.delayMillis = 1500
            f.select(f.document(CHUNK_BYTES * 4))
            f.await { f.offsets.isNotEmpty() }
            val row = f.runtime.rows.value.single()
            val manager = f.target.getSystemService(NotificationManager::class.java)
            f.await { manager.activeNotifications.any { it.id == 3301 && it.notification.actions?.isNotEmpty() == true } }
            manager.activeNotifications.first { it.id == 3301 }.notification.actions.first().actionIntent.send()
            f.await { f.runtime.rows.value.singleOrNull()?.intent == UploadIntent.PAUSED }
            val count = f.offsets.size
            f.shell("input keyevent KEYCODE_HOME")
            f.front()
            f.scenario.recreate()
            Thread.sleep(1800) // Negative assertion: longer than the delayed response; no later chunk may start.
            assertEquals(count, f.offsets.size)
            assertEquals(UploadIntent.PAUSED, f.runtime.rows.value.single().intent)
            f.runtime.resume(row.id)
            f.await { f.runtime.rows.value.singleOrNull()?.phase == UploadPhase.QUEUED }
            assertEquals(1, f.initializationCount.get())
        }
    }
    @Test fun unknownSizeOversizeDoesNotInitializeOrTransfer() {
        UploadDeviceFixture().use { f ->
            f.max = 10
            f.select(f.document(CHUNK_BYTES, unknown = true))
            f.await { f.runtime.rows.value.singleOrNull()?.issue == UploadIssue.OVERSIZE }
            assertEquals(0, f.initializationCount.get())
            assertTrue(f.offsets.isEmpty())
        }
    }
    @Test fun finalizedRefreshesShellInsteadOfClaimingQueuedSuccess() {
        UploadDeviceFixture().use { f ->
            f.select(f.document(3))
            f.await { f.runtime.rows.value.singleOrNull()?.phase == UploadPhase.QUEUED }
            val id = f.runtime.rows.value.single().status!!.uploadId
            val before = f.dashboardReads.get()
            f.uploads[id]!!.phase = "finalized"
            runBlocking { f.runtime.refresh() }
            f.await { f.runtime.rows.value.singleOrNull()?.phase == UploadPhase.FINALIZED && f.dashboardReads.get() > before }
            assertEquals(1, f.initializationCount.get())
        }
    }
}
