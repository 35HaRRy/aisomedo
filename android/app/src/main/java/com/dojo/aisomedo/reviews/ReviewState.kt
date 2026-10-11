package com.dojo.aisomedo.reviews

import com.dojo.aisomedo.api.ReviewDetailOut
import kotlinx.serialization.json.JsonObject
import java.time.Instant
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZoneId

enum class ReviewAction { REVIEW, UPLOAD, SKIP, RESCHEDULE }

data class ReviewTarget(
    val reviewId: Int? = null,
    val occurrenceId: Int? = null,
    val packageFolder: String? = null,
    val expectedVersion: Int? = null,
    val action: ReviewAction = ReviewAction.REVIEW,
) {
    val valid: Boolean get() = (reviewId != null).xor(occurrenceId != null) &&
        (reviewId == null || reviewId > 0) && (occurrenceId == null || occurrenceId > 0 && !packageFolder.isNullOrBlank()) &&
        (expectedVersion == null || expectedVersion > 0) && (packageFolder == null || packageFolder.isNotBlank())
}

enum class ReviewIssue { NETWORK, INVALID_TIME, INVALID_RESPONSE, STALE, ALREADY_HANDLED, NOT_FOUND, UNCERTAIN, PREVIEW, RENDER_FAILED, PACKAGE_CHANGED }

data class ReviewState(
    val target: ReviewTarget? = null,
    val detail: ReviewDetailOut? = null,
    val busy: Boolean = false,
    val readRequired: Boolean = true,
    val previewReady: Boolean = false,
    val issue: ReviewIssue? = null,
    val continuing: Boolean = false,
    val nextRegularAt: String? = null,
    val publication: JsonObject? = null,
) {
    val canDecide: Boolean get() = target?.valid == true && !busy && !readRequired && issue == null &&
        (target.reviewId == null || detail?.review?.let { review ->
            review.status == "pending" && review.id == target.reviewId &&
                (target.packageFolder == null || review.packageFolder == target.packageFolder) &&
                (target.expectedVersion == null || review.version == target.expectedVersion)
        } == true)
    val canApprove: Boolean get() = canDecide && detail?.renderReady == true &&
        !detail.previewUrl.isNullOrBlank() && previewReady
}

fun futureIstanbulInstant(date: LocalDate, time: LocalTime, now: Instant): String? {
    val due = date.atTime(time).atZone(ZoneId.of("Europe/Istanbul")).toOffsetDateTime()
    return due.takeIf { it.toInstant() > now }?.toString()
}
