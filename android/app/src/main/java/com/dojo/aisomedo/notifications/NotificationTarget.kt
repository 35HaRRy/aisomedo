package com.dojo.aisomedo.notifications

import com.dojo.aisomedo.reviews.ReviewAction
import com.dojo.aisomedo.api.DashboardOut

data class NotificationTarget(val type: String, val packageFolder: String, val reviewId: Int? = null,
    val reviewVersion: Int? = null, val occurrenceId: Int? = null, val action: ReviewAction = ReviewAction.REVIEW) {
    fun data(): Map<String, String> = buildMap {
        put("type", type); put("package_folder", packageFolder); put("action", action.name)
        reviewId?.let { put("review_id", it.toString()) }
        reviewVersion?.let { put("review_version", it.toString()) }
        occurrenceId?.let { put("occurrence_id", it.toString()) }
    }
}

fun parseNotificationTarget(data: Map<String, String>): NotificationTarget? {
    val type = data["type"] ?: return null
    val folder = data["package_folder"] ?: return null
    if (folder.length !in 1..128 || folder.isBlank() || folder in setOf(".", "..") ||
        folder.any { it == '/' || it == '\\' || it.isISOControl() }) return null
    fun id(key: String): Int? = data[key]?.takeIf { it.matches(Regex("[0-9]+")) }?.toIntOrNull()?.takeIf { it > 0 }
    val default = if (type == "empty_package") ReviewAction.UPLOAD else ReviewAction.REVIEW
    val action = data["action"]?.let { raw -> ReviewAction.entries.find { it.name == raw } ?: return null } ?: default
    return when (type) {
        "review_required" -> if (action in setOf(ReviewAction.REVIEW, ReviewAction.SKIP, ReviewAction.RESCHEDULE))
            NotificationTarget(type, folder, id("review_id") ?: return null, id("review_version") ?: return null, action = action) else null
        "empty_package" -> if (action in setOf(ReviewAction.UPLOAD, ReviewAction.SKIP, ReviewAction.RESCHEDULE))
            NotificationTarget(type, folder, occurrenceId = id("occurrence_id") ?: return null, action = action) else null
        "publication_confirmed", "publication_failed" -> if (action == ReviewAction.REVIEW) NotificationTarget(type, folder) else null
        else -> null
    }
}

enum class PushAvailability { UNCONFIGURED, SERVICES_UNAVAILABLE, PERMISSION_DENIED, REGISTERING, AVAILABLE, REGISTRATION_FAILED }
data class PushFailure(val origin: String, val bindingId: String, val status: Int, val updateUrl: String? = null)
data class PushReceipt(val origin: String, val bindingId: String)

internal fun registrationAvailability(base: PushAvailability, ready: Boolean, failure: PushFailure?): PushAvailability = when {
    base != PushAvailability.AVAILABLE -> base
    failure != null -> PushAvailability.REGISTRATION_FAILED
    ready -> PushAvailability.AVAILABLE
    else -> PushAvailability.REGISTERING
}

internal fun NotificationTarget.isPendingIn(dashboard: DashboardOut): Boolean = when (type) {
    "review_required" -> dashboard.pendingActions.any { it.reviewId == reviewId && it.version == reviewVersion &&
        it.packageFolder == packageFolder && it.state == "review_ready" }
    "empty_package" -> dashboard.pendingActions.any { it.occurrenceId == occurrenceId &&
        it.packageFolder == packageFolder && it.state == "empty_package" }
    else -> true // Publication outcomes are history, not pending decisions.
}
