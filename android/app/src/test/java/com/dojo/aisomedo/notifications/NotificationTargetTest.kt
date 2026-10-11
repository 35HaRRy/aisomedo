package com.dojo.aisomedo.notifications

import com.dojo.aisomedo.reviews.ReviewAction
import org.junit.Assert.*
import org.junit.Test

class NotificationTargetTest {
    private val review = mapOf("type" to "review_required", "review_id" to "7", "review_version" to "3", "package_folder" to "active")
    @Test fun validReviewEmptyAndOutcomesRouteWithoutAnApproveAction() {
        assertEquals(NotificationTarget("review_required", "active", 7, 3), parseNotificationTarget(review))
        assertEquals(ReviewAction.SKIP, parseNotificationTarget(review + ("action" to "SKIP"))!!.action)
        assertEquals(ReviewAction.UPLOAD, parseNotificationTarget(mapOf("type" to "empty_package", "occurrence_id" to "2", "package_folder" to "active"))!!.action)
        for (type in listOf("publication_confirmed", "publication_failed")) {
            assertEquals(type, parseNotificationTarget(mapOf("type" to type, "package_folder" to "active"))!!.type)
            assertNull(parseNotificationTarget(mapOf("type" to type, "package_folder" to "active", "action" to "SKIP")))
        }
    }
    @Test fun unknownMalformedAndOverflowedPayloadsCannotRoute() {
        assertNull(parseNotificationTarget(mapOf("type" to "approve", "review_id" to "7")))
        for (key in review.keys) assertNull(parseNotificationTarget(review - key))
        for (id in listOf("0", "-1", "2147483648", "7.0", " 7", "not-id")) {
            assertNull(parseNotificationTarget(review + ("review_id" to id)))
            assertNull(parseNotificationTarget(review + ("review_version" to id)))
        }
        for (folder in listOf("", " ", ".", "..", "/active", "active\\path", "a\n", "a\u007f", "a".repeat(129)))
            assertNull(parseNotificationTarget(review + ("package_folder" to folder)))
        for (action in listOf("approve", "APPROVE", "UPLOAD", "skip", "", " RESCHEDULE"))
            assertNull(parseNotificationTarget(review + ("action" to action)))
    }
    @Test fun payloadRoundtripRetainsExactShortcutIdentity() {
        val target = parseNotificationTarget(review + ("action" to "RESCHEDULE"))!!
        assertEquals(target, parseNotificationTarget(target.data()))
        assertNotEquals(target, target.copy(action = ReviewAction.SKIP))
    }
}
