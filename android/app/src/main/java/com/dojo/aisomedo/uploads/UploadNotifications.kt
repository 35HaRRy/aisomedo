package com.dojo.aisomedo.uploads

import android.app.*
import android.content.*
import android.net.Uri
import androidx.core.app.NotificationCompat
import com.dojo.aisomedo.MainActivity
import com.dojo.aisomedo.R

internal fun phaseLabel(phase: UploadPhase): Int = when (phase) {
    UploadPhase.WAITING -> R.string.upload_waiting; UploadPhase.PREPARING -> R.string.upload_preparing
    UploadPhase.UPLOADING -> R.string.upload_transferring; UploadPhase.PAUSED -> R.string.upload_paused
    UploadPhase.RETRYABLE -> R.string.upload_retryable; UploadPhase.NEEDS_FILE -> R.string.upload_needs_file
    UploadPhase.QUEUED -> R.string.upload_queued; UploadPhase.PROCESSING -> R.string.upload_processing
    UploadPhase.FINALIZED -> R.string.upload_finalized; UploadPhase.FAILED -> R.string.upload_failed
    UploadPhase.CONFLICT -> R.string.upload_conflict; UploadPhase.EXPIRED -> R.string.upload_expired
    UploadPhase.SKIPPED -> R.string.upload_skipped
}
class UploadNotifications(private val context: Context) {
    private val manager = context.getSystemService(NotificationManager::class.java)
    private var last = 0L
    private var lastPhase: UploadPhase? = null
    init { manager.createNotificationChannel(NotificationChannel("dojo-uploads", context.getString(R.string.upload_channel), NotificationManager.IMPORTANCE_LOW)) }
    fun visible() = manager.areNotificationsEnabled() && manager.getNotificationChannel("dojo-uploads")?.importance != NotificationManager.IMPORTANCE_NONE
    fun build(row: UploadRecord?): Notification {
        val tap = Intent(context, MainActivity::class.java).putExtra("destination", "PACKAGE")
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        val builder = NotificationCompat.Builder(context, "dojo-uploads")
            .setSmallIcon(R.drawable.ic_upload).setContentTitle(context.getString(R.string.upload_notification_title))
            .setContentText(row?.filename ?: context.getString(R.string.upload_waiting))
            .setContentIntent(PendingIntent.getActivity(context, 3301, tap, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE))
            .setOngoing(true).setOnlyAlertOnce(true).setCategory(NotificationCompat.CATEGORY_PROGRESS)
        if (row != null) {
            val total = row.size ?: 0
            val received = row.status?.receivedBytes ?: 0
            val percent = if (total > 0) (received.toDouble() / total * 100).toInt().coerceIn(0, 100) else 0
            val text = context.getString(phaseLabel(row.phase)) + if (total > 0 && row.phase != UploadPhase.PREPARING) " · " + context.getString(R.string.upload_bytes, received, total, percent) else ""
            builder.setSubText(text).setProgress(100, percent, row.phase == UploadPhase.PREPARING || total == 0L)
            if (eligible(row)) {
                val pause = Intent(context, UploadPauseReceiver::class.java).setAction("com.dojo.aisomedo.PAUSE_UPLOAD")
                    .setData(Uri.parse("dojo-upload://${row.bindingId}/${row.id}"))
                    .putExtra("binding", row.bindingId).putExtra("row", row.id)
                builder.addAction(R.drawable.ic_upload, context.getString(R.string.upload_pause), PendingIntent.getBroadcast(context, 0, pause, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE))
            }
        }
        return builder.build()
    }
    fun update(row: UploadRecord) {
        val time = android.os.SystemClock.elapsedRealtime()
        if (time - last < 1000 && lastPhase == row.phase) return
        last = time; lastPhase = row.phase
        manager.notify(3301, build(row))
    }
}
class UploadPauseReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val id = intent.getStringExtra("row") ?: return
        val binding = intent.getStringExtra("binding") ?: return
        val runtime = UploadRuntime.get(context)
        if (runtime.rows.value.any { it.id == id && it.bindingId == binding }) runtime.pause(id)
    }
}
