package com.dojo.aisomedo.notifications

import android.app.*
import android.content.*
import android.net.Uri
import android.os.Bundle
import androidx.core.app.NotificationCompat
import com.dojo.aisomedo.MainActivity
import com.dojo.aisomedo.R
import com.dojo.aisomedo.api.DashboardOut
import com.dojo.aisomedo.reviews.ReviewAction
import com.dojo.aisomedo.uploads.UploadRuntime

class ReviewNotifications(private val context: Context) {
    private val manager = context.getSystemService(NotificationManager::class.java)
    init {
        manager.createNotificationChannel(NotificationChannel("dojo-reviews", context.getString(R.string.review_channel), NotificationManager.IMPORTANCE_HIGH))
        manager.createNotificationChannel(NotificationChannel("dojo-publications", context.getString(R.string.publication_channel), NotificationManager.IMPORTANCE_DEFAULT))
    }
    fun intent(target: NotificationTarget, origin: String, bindingId: String): Intent = Intent(context, MainActivity::class.java)
        .setData(Uri.Builder().scheme("dojo-review").authority(bindingId).appendPath(target.type)
            .appendPath((target.reviewId ?: target.occurrenceId ?: target.packageFolder).toString())
            .appendPath(target.reviewVersion?.toString() ?: "").appendPath(target.packageFolder).appendPath(target.action.name).build())
        .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        .putExtra("notification_origin", origin).putExtra("notification_binding", bindingId).apply {
            target.data().forEach { (key, value) -> putExtra(key, value) }
        }
    fun pendingIntent(target: NotificationTarget, origin: String, bindingId: String): PendingIntent = PendingIntent.getActivity(
        context, 0, intent(target, origin, bindingId), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    fun show(target: NotificationTarget, title: String, body: String, bindingId: String) {
        if (!manager.areNotificationsEnabled()) return
        val store = UploadRuntime.get(context).sessionStore
        val origin = runCatching { store.origin }.getOrNull() ?: return
        if (runCatching { store.readSession(origin)?.bindingId }.getOrNull() != bindingId) return
        val actionable = target.type in setOf("review_required", "empty_package")
        val channel = if (actionable) "dojo-reviews" else "dojo-publications"
        val builder = NotificationCompat.Builder(context, channel).setSmallIcon(R.drawable.ic_review)
            .setContentTitle(title.take(256)).setContentText(body.take(2048)).setStyle(NotificationCompat.BigTextStyle().bigText(body.take(2048)))
            .setAutoCancel(true).setContentIntent(pendingIntent(target, origin, bindingId))
            .addExtras(Bundle().apply {
                target.data().forEach { (key, value) -> putString(key, value) }
                putString("notification_origin", origin); putString("notification_binding", bindingId)
            })
        if (actionable) for (action in listOf(target.action, ReviewAction.SKIP, ReviewAction.RESCHEDULE).distinct()) {
            val label = when (action) { ReviewAction.SKIP -> R.string.review_skip; ReviewAction.RESCHEDULE -> R.string.review_reschedule
                ReviewAction.UPLOAD -> R.string.review_upload; else -> R.string.review_open }
            builder.addAction(R.drawable.ic_review, context.getString(label), pendingIntent(target.copy(action = action), origin, bindingId))
        }
        val tag = target.reviewId?.let { "review:$it" } ?: target.occurrenceId?.let { "occurrence:$it" } ?: "publication:${target.packageFolder}"
        try { manager.notify(tag, 3601, builder.build()) } catch (_: SecurityException) { /* Permission changed after check. */ }
    }
    fun cancelReview(id: Int) { manager.cancel("review:$id", 3601) }
    fun cancelOccurrence(id: Int) { manager.cancel("occurrence:$id", 3601) }
    fun reconcile(dashboard: DashboardOut, origin: String, bindingId: String) {
        manager.activeNotifications.filter { it.id == 3601 }.forEach { item ->
            val extras = item.notification.extras
            val data = extras.keySet().mapNotNull { key -> (extras.get(key) as? String)?.let { key to it } }.toMap()
            val target = parseNotificationTarget(data)
            if (data["notification_origin"] != origin || data["notification_binding"] != bindingId ||
                target == null || !target.isPendingIn(dashboard)) manager.cancel(item.tag, item.id)
        }
    }
    fun clear() { manager.activeNotifications.filter { it.id == 3601 || it.notification.channelId == "dojo-publications" }.forEach { manager.cancel(it.tag, it.id) } }
}
