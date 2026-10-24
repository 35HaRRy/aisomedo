package com.dojo.aisomedo.reviews

import com.dojo.aisomedo.api.ReviewDetailOut
import com.dojo.aisomedo.api.ReviewOut
import org.junit.Assert.*
import org.junit.Test
import java.time.Instant
import java.time.LocalDate
import java.time.LocalTime
import java.time.OffsetDateTime

class ReviewStateTest {
    private val detail = ReviewDetailOut(null, "/api/packages/active/render/preview?revision=exact", true,
        ReviewOut("Exact caption\n#dojo", "2026-10-11T10:00:00+03:00", 7, null, 2, "active", "exact", "pending", 3))
    private val prepared = ReviewState(target = ReviewTarget(reviewId = 7, packageFolder = "active", expectedVersion = 3),
        detail = detail, readRequired = false, previewReady = true)

    @Test fun onlyPreparedCurrentPendingPreviewCanApprove() {
        assertTrue(prepared.canApprove)
        assertFalse(prepared.copy(previewReady = false).canApprove)
        assertFalse(prepared.copy(readRequired = true).canApprove)
        assertFalse(prepared.copy(busy = true).canApprove)
        assertFalse(prepared.copy(issue = ReviewIssue.STALE).canApprove)
        assertFalse(prepared.copy(detail = detail.copy(renderReady = false)).canApprove)
        assertFalse(prepared.copy(detail = detail.copy(previewUrl = null)).canApprove)
        assertFalse(prepared.copy(detail = detail.copy(review = detail.review.copy(status = "skipped"))).canApprove)
        assertFalse(prepared.copy(target = ReviewTarget(reviewId = 8)).canApprove)
        assertFalse(prepared.copy(target = ReviewTarget(reviewId = 7, packageFolder = "old")).canApprove)
        assertFalse(prepared.copy(target = ReviewTarget(reviewId = 7, expectedVersion = 2)).canApprove)
    }

    @Test fun targetsRequireExactlyOnePositiveId() {
        assertFalse(ReviewTarget().valid)
        assertFalse(ReviewTarget(reviewId = -1).valid)
        assertFalse(ReviewTarget(reviewId = 7, occurrenceId = 2).valid)
        assertFalse(ReviewTarget(occurrenceId = 2).valid)
        assertTrue(ReviewTarget(occurrenceId = 2, packageFolder = "active").valid)
        assertTrue(ReviewTarget(reviewId = 7).valid)
    }

    @Test fun failedAndUncertainAllowDecisionsButPublishingDoesNot() {
        for (status in listOf("failed", "uncertain")) {
            val state = prepared.copy(detail = detail.copy(review = detail.review.copy(status = status)))
            assertTrue(state.canDecide)
            assertTrue(state.canApprove)
        }
        val publishing = prepared.copy(detail = detail.copy(review = detail.review.copy(status = "publishing")))
        assertFalse(publishing.canDecide)
        assertFalse(publishing.canApprove)
    }

    @Test fun rescheduleUsesIstanbulAndRejectsNowAndPast() {
        val date = LocalDate.of(2026, 10, 11)
        val time = LocalTime.of(10, 0)
        val exact = Instant.parse("2026-10-11T07:00:00Z")
        assertNull(futureIstanbulInstant(date, time, exact))
        assertNull(futureIstanbulInstant(date, time, exact.plusSeconds(1)))
        val future = futureIstanbulInstant(date, time, exact.minusSeconds(1))!!
        assertEquals("+03:00", OffsetDateTime.parse(future).offset.toString())
        assertEquals(exact, OffsetDateTime.parse(future).toInstant())
    }

    @Test fun rescheduleMustBeStrictlyBeforeNextRegularTime() {
        val now = Instant.parse("2026-10-11T07:00:00Z")
        val limit = "2026-10-12T10:00:00+03:00"
        assertNull(futureIstanbulInstant(LocalDate.of(2026, 10, 12), LocalTime.of(10, 0), now, limit))
        assertNull(futureIstanbulInstant(LocalDate.of(2026, 10, 13), LocalTime.of(10, 0), now, limit))
        assertNotNull(futureIstanbulInstant(LocalDate.of(2026, 10, 12), LocalTime.of(9, 59), now, limit))
    }
}
