package com.dojo.aisomedo.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.test.espresso.Espresso
import androidx.test.espresso.UiController
import androidx.test.espresso.ViewAction
import androidx.test.espresso.action.ViewActions.click
import androidx.test.espresso.matcher.ViewMatchers.isAssignableFrom
import androidx.test.espresso.matcher.ViewMatchers.withId
import android.view.View
import android.widget.DatePicker
import android.widget.TimePicker
import com.dojo.aisomedo.AppUiState
import com.dojo.aisomedo.Phase
import com.dojo.aisomedo.api.*
import com.dojo.aisomedo.reviews.*
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

class ReviewScreenTest {
    @get:Rule val compose = createComposeRule()
    private val detail = ReviewDetailOut("2099-10-19T10:00:00+03:00", "/api/packages/active/render/preview", true,
        ReviewOut("Exact caption\n#dojo", "2026-10-11T10:00:00+03:00", 7, 2, "active", "exact", "pending", 3))
    private val initial = ReviewState(target = ReviewTarget(reviewId = 7), detail = detail, readRequired = false)

    @Test fun exactCaptionAndSkipConfirmationAreVisibleWithoutImplicitMutation() {
        var skips = 0
        compose.setContent {
            var state by remember { mutableStateOf(initial) }
            DojoTheme { Column(Modifier.verticalScroll(rememberScrollState())) {
                ReviewScreen(state, true, { state = state.copy(target = state.target!!.copy(action = it)) }, {}, { skips++ }, { _, _ -> }, {}, {}, {})
            } }
        }
        compose.onNodeWithText("Exact caption\n#dojo").assertIsDisplayed()
        compose.onNodeWithTag("review-approve").assertIsNotEnabled()
        compose.onNodeWithTag("review-skip").performScrollTo().performClick()
        assertEquals(0, skips)
        compose.onNodeWithText("Bu Yayın Zamanı atlanacak; Dojo Yayın Planı değişmez.").assertIsDisplayed()
        compose.onNodeWithTag("review-confirm-skip").performClick()
        assertEquals(1, skips)
    }

    @Test fun staleHandledAndLoadingReviewsCannotApprove() {
        val current = mutableStateOf(initial.copy(previewReady = true))
        compose.setContent { DojoTheme { ReviewScreen(current.value, true, {}, {}, {}, { _, _ -> }, {}, {}, {}) } }
        compose.onNodeWithTag("review-approve").assertIsEnabled()
        for (state in listOf(initial.copy(busy = true), initial.copy(issue = ReviewIssue.STALE),
            initial.copy(detail = detail.copy(review = detail.review.copy(status = "skipped"))))) {
            compose.runOnIdle { current.value = state }
            compose.onNodeWithTag("review-approve").assertIsNotEnabled()
        }
    }

    @Test fun cancellingNativeDateSelectionNeverSubmitsReschedule() {
        var decisions = 0
        compose.setContent { DojoTheme { Column(Modifier.verticalScroll(rememberScrollState())) {
            ReviewScreen(initial.copy(target = initial.target!!.copy(action = ReviewAction.RESCHEDULE)), true,
                {}, {}, {}, { _, _ -> decisions++ }, {}, {}, {})
        } } }
        compose.onNodeWithTag("review-date").performScrollTo().performClick()
        Espresso.pressBack()
        assertEquals(0, decisions)
        compose.onNodeWithTag("review-time").performScrollTo().performClick()
        Espresso.pressBack()
        assertEquals(0, decisions)
    }

    @Test fun openDateDialogCannotEditDraftAfterLosingAuthority() {
        pickerConfirmationAfterLosingAuthority("review-date", DatePicker::class.java) { view ->
            (view as DatePicker).updateDate(2099, 0, 15)
        }
    }

    @Test fun openTimeDialogCannotEditDraftAfterLosingAuthority() {
        pickerConfirmationAfterLosingAuthority("review-time", TimePicker::class.java) { view ->
            (view as TimePicker).apply { hour = 14; minute = 35 }
        }
    }

    private fun pickerConfirmationAfterLosingAuthority(tag: String, type: Class<out View>, select: (View) -> Unit) {
        val current = mutableStateOf(AppUiState(phase = Phase.READY, authoritative = true,
            review = initial.copy(target = initial.target!!.copy(action = ReviewAction.RESCHEDULE))))
        var decisions = 0
        var cancelled = false
        compose.setContent { DojoTheme { Column(Modifier.verticalScroll(rememberScrollState())) {
            ReviewScreen(current.value.review, current.value.canMutate, { cancelled = it == ReviewAction.REVIEW }, {}, {},
                { _, _ -> decisions++ }, {}, {}, {})
        } } }
        val field = compose.onNodeWithTag(tag).performScrollTo()
        val original = field.fetchSemanticsNode().config[SemanticsProperties.Text].single().text
        field.performClick()
        Espresso.onView(isAssignableFrom(type)).perform(object : ViewAction {
            override fun getConstraints() = isAssignableFrom(type)
            override fun getDescription() = "Select different picker value"
            override fun perform(uiController: UiController, view: View) { select(view); uiController.loopMainThreadUntilIdle() }
        })
        compose.runOnIdle { current.value = current.value.copy(authoritative = false) }
        // Dialog may dismiss, but its old callback must not update read-only draft.
        Espresso.onView(withId(android.R.id.button1)).perform(click())
        field.assertTextEquals(original).assertIsNotEnabled()
        compose.onNodeWithTag("review-confirm-reschedule").assertIsNotEnabled()
        assertEquals(0, decisions)
        compose.onNodeWithText("Vazgeç").assertIsEnabled().performScrollTo().performClick()
        compose.runOnIdle { assertTrue(cancelled) }
        compose.onNodeWithTag("review-close").assertIsEnabled()
    }

    @Test fun unavailableInboxIsNotAnEmptyInbox() {
        val dashboard = mutableStateOf<DashboardOut?>(null)
        compose.setContent { DojoTheme { ApprovalInbox(dashboard.value, false, {}, { _, _ -> }) } }
        compose.onNodeWithText("Bilgiler henüz alınamadı. Tekrar deneyin.").assertExists()
        compose.onNodeWithText("Bekleyen işlem yok").assertDoesNotExist()
        compose.runOnIdle { dashboard.value = DashboardOut("2026-10-11T10:00:00+03:00", DashboardInstagramOut("unknown"), null,
            null, emptyList(), PlanOut(null, null, false, "Europe/Istanbul"), DashboardWorkerOut(null, "unknown")) }
        compose.onNodeWithText("Bekleyen işlem yok").assertExists()
    }
}
