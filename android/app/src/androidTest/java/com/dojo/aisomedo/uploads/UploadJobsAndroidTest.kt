package com.dojo.aisomedo.uploads

import android.app.job.JobScheduler
import android.content.Intent
import android.os.Build
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test

class UploadJobsAndroidTest {
    @Test fun notificationIntentIsExplicitImmutableAndBindingScoped() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val row = UploadRecord("00000000-0000-0000-0000-000000000033", "https://example.com", "a".repeat(64), "content://test/file", "file.jpg", "image/jpeg", 1, 2)
        val notification = UploadNotifications(context).build(row)
        assertNotNull(notification.contentIntent)
        assertEquals(1, notification.actions.size)
        if (Build.VERSION.SDK_INT >= 31) assertTrue(notification.actions.single().actionIntent.isImmutable)
    }
    @Test fun staleBindingCannotCancelDifferentUidtJob() {
        if (Build.VERSION.SDK_INT < 34) return
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val scheduler = context.getSystemService(JobScheduler::class.java).forNamespace("dojo-uploads")
        val pending = scheduler.getPendingJob(3300) ?: return
        val binding = pending.extras.getString("binding")!!
        UploadScheduler(context).cancel(if (binding == "a".repeat(64)) "b".repeat(64) else "a".repeat(64))
        assertEquals(binding, scheduler.getPendingJob(3300)!!.extras.getString("binding"))
    }
    @Test fun malformedPauseCannotChangeSession() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val runtime = UploadRuntime.get(context)
        val rows = runtime.rows.value
        UploadPauseReceiver().onReceive(context, Intent(context, UploadPauseReceiver::class.java).putExtra("binding", "wrong").putExtra("row", "wrong"))
        assertEquals(rows, runtime.rows.value)
    }
}
