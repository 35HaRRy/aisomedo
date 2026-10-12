package com.dojo.aisomedo.notifications

import android.app.NotificationManager
import android.os.Build
import androidx.test.platform.app.InstrumentationRegistry
import com.dojo.aisomedo.reviews.ReviewAction
import com.dojo.aisomedo.uploads.UploadDeviceFixture
import com.dojo.aisomedo.uploads.UploadNotifications
import com.dojo.aisomedo.AppViewModel
import com.dojo.aisomedo.MainActivity
import com.dojo.aisomedo.Destination
import androidx.lifecycle.ViewModelProvider
import org.junit.Assert.*
import org.junit.Test

class ReviewNotificationsTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    @Test fun authoritativeReconciliationRemovesResolvedAndReplacedTargetsButKeepsUploads() {
        UploadDeviceFixture().use { fixture ->
            val manager = context.getSystemService(NotificationManager::class.java)
            val renderer = ReviewNotifications(context)
            val dashboard = kotlinx.serialization.json.Json.decodeFromString<com.dojo.aisomedo.api.DashboardOut>("""{"generated_at":"now","package":null,"next_slot":null,"pending_actions":[],"plan":{"anchor_date":null,"anchor_time":null,"enabled":false,"timezone":"Europe/Istanbul"},"instagram":{"health":"unknown"},"worker":{"phase":null,"status":"unknown"}}""")
            try {
                renderer.show(NotificationTarget("review_required", "active", 7, 3), "Review", "body", fixture.binding)
                renderer.show(NotificationTarget("empty_package", "active", occurrenceId = 2, action = ReviewAction.UPLOAD), "Empty", "body", fixture.binding)
                manager.notify(3301, UploadNotifications(context).build(null))
                assertTrue(manager.activeNotifications.any { it.tag == "review:7" })
                renderer.reconcile(dashboard, fixture.origin, fixture.binding)
                assertTrue(manager.activeNotifications.none { it.tag == "review:7" || it.tag == "occurrence:2" })
                assertTrue(manager.activeNotifications.any { it.id == 3301 })
            } finally { renderer.clear(); manager.cancel(3301) }
        }
    }
    @Test fun shortcutsAreExplicitImmutableAndDistinct() {
        val renderer = ReviewNotifications(context)
        val target = NotificationTarget("review_required", "active", 7, 3)
        val review = renderer.pendingIntent(target, "https://dojo.example", "binding")
        val skip = renderer.pendingIntent(target.copy(action = ReviewAction.SKIP), "https://dojo.example", "binding")
        val reschedule = renderer.pendingIntent(target.copy(action = ReviewAction.RESCHEDULE), "https://dojo.example", "binding")
        assertNotEquals(review, skip); assertNotEquals(skip, reschedule)
        if (Build.VERSION.SDK_INT >= 31) { assertTrue(review.isImmutable); assertTrue(skip.isImmutable) }
        val intent = renderer.intent(target.copy(action = ReviewAction.SKIP), "https://dojo.example", "binding")
        assertEquals("com.dojo.aisomedo.MainActivity", intent.component!!.className)
        assertEquals("SKIP", intent.getStringExtra("action"))
        assertEquals("binding", intent.getStringExtra("notification_binding"))
        assertNotEquals(intent.data, renderer.intent(target, "https://dojo.example", "binding").data)
    }
    @Test fun duplicatePayloadReplacesSameTagAndClearPreservesUploadNotification() {
        UploadDeviceFixture().use { fixture ->
        val manager = context.getSystemService(NotificationManager::class.java)
        assertTrue(manager.areNotificationsEnabled())
        val renderer = ReviewNotifications(context)
        try {
            val target = NotificationTarget("review_required", "active", 7, 3)
            renderer.show(target, "First", "body", fixture.binding)
            renderer.show(target, "Second", "body", fixture.binding)
            assertEquals(1, manager.activeNotifications.count { it.tag == "review:7" })
            renderer.cancelReview(7)
            assertTrue(manager.activeNotifications.none { it.tag == "review:7" })
            renderer.show(NotificationTarget("empty_package", "active", occurrenceId = 2, action = ReviewAction.UPLOAD), "Empty", "body", fixture.binding)
            manager.notify(3301, UploadNotifications(context).build(null))
            renderer.clear()
            assertTrue(manager.activeNotifications.none { it.tag?.startsWith("occurrence:") == true })
            assertTrue(manager.activeNotifications.any { it.id == 3301 })
        } finally { renderer.clear(); manager.cancel(3301) }
        }
    }
    @Test fun warmExplicitShortcutAndRecreationNeverSubmitACommand() {
        UploadDeviceFixture().use { fixture ->
            val intent = ReviewNotifications(context).intent(NotificationTarget("review_required", "active", 7, 3,
                action = ReviewAction.SKIP), fixture.origin, fixture.binding)
            fixture.scenario.onActivity { activity -> activity.startActivity(intent) }
            val deadline = System.currentTimeMillis() + 10000
            var target: com.dojo.aisomedo.reviews.ReviewTarget? = null
            while (target == null && System.currentTimeMillis() < deadline) {
                fixture.scenario.onActivity { target = ViewModelProvider(it)[AppViewModel::class.java].state.value.review.target }
                Thread.sleep(20)
            }
            assertEquals(7, target?.reviewId); assertEquals(ReviewAction.SKIP, target?.action)
            fixture.scenario.recreate()
            target = null
            val restoredDeadline = System.currentTimeMillis() + 10000
            while (target == null && System.currentTimeMillis() < restoredDeadline) {
                fixture.scenario.onActivity { target = ViewModelProvider(it)[AppViewModel::class.java].state.value.review.target }
                Thread.sleep(20)
            }
            assertEquals(ReviewAction.SKIP, target?.action)
            assertEquals(0, fixture.initializationCount.get())
        }
    }
    @Test fun mixedOutcomeLauncherExtrasOpenActivityContext() {
        UploadDeviceFixture().use { fixture ->
            val intent = android.content.Intent(context, MainActivity::class.java)
                .addFlags(android.content.Intent.FLAG_ACTIVITY_SINGLE_TOP or android.content.Intent.FLAG_ACTIVITY_CLEAR_TOP)
                .putExtra("type", "publication_confirmed").putExtra("package_folder", "completed-synthetic")
            fixture.scenario.onActivity { it.startActivity(intent) }
            val deadline = System.currentTimeMillis() + 10000
            var selected: String? = null
            while (selected == null && System.currentTimeMillis() < deadline) {
                fixture.scenario.onActivity {
                    val state = ViewModelProvider(it)[AppViewModel::class.java].state.value
                    selected = state.outcomePackage
                    if (selected != null) assertEquals(Destination.ACTIVITY, state.destination)
                }
                Thread.sleep(20)
            }
            assertEquals("completed-synthetic", selected)
            assertEquals(0, fixture.initializationCount.get())
        }
    }
    @Test fun coldExplicitLaunchWaitsForAuthenticatedReadWithoutSubmitting() {
        UploadDeviceFixture().use { fixture ->
            fixture.scenario.close()
            val intent = ReviewNotifications(context).intent(NotificationTarget("review_required", "active", 7, 3,
                action = ReviewAction.RESCHEDULE), fixture.origin, fixture.binding)
                .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
            androidx.test.core.app.ActivityScenario.launch<MainActivity>(intent).use { scenario ->
                val deadline = System.currentTimeMillis() + 10000
                var target: com.dojo.aisomedo.reviews.ReviewTarget? = null
                while (target == null && System.currentTimeMillis() < deadline) {
                    scenario.onActivity { target = ViewModelProvider(it)[AppViewModel::class.java].state.value.review.target }
                    Thread.sleep(20)
                }
                assertEquals(7, target?.reviewId); assertEquals(ReviewAction.RESCHEDULE, target?.action)
                assertEquals(0, fixture.initializationCount.get())
            }
        }
    }
    @Test fun unconfiguredRuntimeCanRefreshWithoutFirebaseInitializationOrNetwork() {
        val runtime = PushRuntime.get(context)
        runtime.refresh()
        assertTrue(runtime.availability.value in setOf(PushAvailability.UNCONFIGURED, PushAvailability.SERVICES_UNAVAILABLE, PushAvailability.PERMISSION_DENIED))
    }
}
