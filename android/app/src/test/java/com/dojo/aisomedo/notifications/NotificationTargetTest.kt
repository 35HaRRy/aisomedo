package com.dojo.aisomedo.notifications

import com.dojo.aisomedo.reviews.ReviewAction
import org.junit.Assert.*
import org.junit.Test

class NotificationTargetTest {
    @Test fun dashboardReconciliationRequiresExactFolderVersionAndReadyState() {
        val dashboard = kotlinx.serialization.json.Json { ignoreUnknownKeys = true }.decodeFromString<com.dojo.aisomedo.api.DashboardOut>("""{"generated_at":"now","package":null,"next_slot":null,"pending_actions":[{"due_at":"now","occurrence_id":2,"package_folder":"active","review_id":7,"state":"review_ready","version":3},{"due_at":"now","occurrence_id":4,"package_folder":"empty","review_id":null,"state":"empty_package","version":null}],"plan":{"anchor_date":null,"anchor_time":null,"enabled":false,"timezone":"Europe/Istanbul"},"instagram":{"health":"unknown"},"worker":{"phase":null,"status":"unknown"}}""")
        val review = NotificationTarget("review_required", "active", 7, 3)
        assertTrue(review.isPendingIn(dashboard))
        assertFalse(review.copy(reviewVersion = 2).isPendingIn(dashboard))
        assertFalse(review.copy(packageFolder = "replacement").isPendingIn(dashboard))
        assertFalse(review.copy(reviewId = 8).isPendingIn(dashboard))
        assertFalse(review.isPendingIn(dashboard.copy(pendingActions = emptyList())))
        val empty = NotificationTarget("empty_package", "empty", occurrenceId = 4, action = ReviewAction.UPLOAD)
        assertTrue(empty.isPendingIn(dashboard))
        assertFalse(empty.copy(packageFolder = "old").isPendingIn(dashboard))
        assertFalse(empty.isPendingIn(dashboard.copy(pendingActions = dashboard.pendingActions.map { it.copy(state = "preparing") })))
        assertTrue(NotificationTarget("publication_confirmed", "completed").isPendingIn(dashboard))
    }
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
