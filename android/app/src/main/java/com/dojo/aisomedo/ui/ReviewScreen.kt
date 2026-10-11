package com.dojo.aisomedo.ui

import android.app.DatePickerDialog
import android.app.TimePickerDialog
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.*
import androidx.compose.ui.unit.dp
import com.dojo.aisomedo.R
import com.dojo.aisomedo.api.ReviewDetailOut
import com.dojo.aisomedo.reviews.*
import com.dojo.aisomedo.uploads.UploadRecord
import java.time.*

@Composable fun ReviewScreen(state: ReviewState, enabled: Boolean, onAction: (ReviewAction) -> Unit,
    onApprove: () -> Unit, onSkip: () -> Unit, onReschedule: (LocalDate, LocalTime) -> Unit,
    onRefresh: () -> Unit, onClose: () -> Unit, preview: @Composable (ReviewDetailOut) -> Unit) {
    val target = state.target ?: return
    Column(Modifier.fillMaxWidth().widthIn(max = 720.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Heading(R.string.review_title)
        TextButton(onClick = onClose, modifier = Modifier.testTag("review-close")) { Text(stringResource(R.string.close)) }
        target.packageFolder?.let { Text(it, style = MaterialTheme.typography.titleMedium) }
        if (state.busy) LinearProgressIndicator(Modifier.fillMaxWidth().semantics { liveRegion = LiveRegionMode.Polite })
        state.issue?.let { Text(stringResource(reviewIssueLabel(it)), color = MaterialTheme.colorScheme.error,
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }) }
        val detail = state.detail
        if (detail != null) {
            Text(stringResource(when (detail.review.status) {
                "approved" -> R.string.review_approved; "skipped" -> R.string.review_skipped
                "rescheduled" -> R.string.review_rescheduled; else -> R.string.review_ready
            }))
            if (detail.renderReady && state.issue == null) preview(detail)
            else if (!detail.renderReady) Text(stringResource(R.string.preparing))
            SectionHeading(R.string.review_caption)
            SelectionContainer { Text(detail.review.caption.orEmpty()) }
            Button(onClick = onApprove, enabled = enabled && state.canApprove, modifier = Modifier.testTag("review-approve")) { Text(stringResource(R.string.review_approve)) }
        } else {
            Text(stringResource(if (target.occurrenceId != null) R.string.empty_package else R.string.loading))
            if (target.occurrenceId != null) Button(onClick = { onAction(ReviewAction.UPLOAD) }, enabled = enabled && !state.busy) { Text(stringResource(R.string.review_upload)) }
        }
        state.publication?.get("state")?.let { value ->
            Text(stringResource(when (value.toString().trim('"')) {
                "confirmed" -> R.string.publication_confirmed; "failed" -> R.string.publication_failed
                else -> R.string.publication_pending
            }), modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
        }
        state.nextRegularAt?.let { Text(stringResource(R.string.review_next_regular, formattedTime(it))) }
        if (detail?.review?.status == "pending" || target.occurrenceId != null) {
            OutlinedButton(onClick = { onAction(ReviewAction.SKIP) }, enabled = enabled && state.canDecide, modifier = Modifier.testTag("review-skip")) { Text(stringResource(R.string.review_skip)) }
            OutlinedButton(onClick = { onAction(ReviewAction.RESCHEDULE) }, enabled = enabled && state.canDecide, modifier = Modifier.testTag("review-reschedule")) { Text(stringResource(R.string.review_reschedule)) }
            when (target.action) {
                ReviewAction.SKIP -> {
                    Text(stringResource(R.string.review_skip_warning))
                    Button(onClick = onSkip, enabled = enabled && state.canDecide, modifier = Modifier.testTag("review-confirm-skip")) { Text(stringResource(R.string.review_confirm_skip)) }
                    TextButton(onClick = { onAction(ReviewAction.REVIEW) }, enabled = !state.busy) { Text(stringResource(R.string.cancel)) }
                }
                ReviewAction.RESCHEDULE -> RescheduleForm(state, enabled, onReschedule) { onAction(ReviewAction.REVIEW) }
                else -> Unit
            }
        }
        TextButton(onClick = onRefresh, enabled = !state.busy, modifier = Modifier.testTag("review-refresh")) { Text(stringResource(R.string.refresh)) }
    }
}

@Composable private fun RescheduleForm(state: ReviewState, enabled: Boolean, onSubmit: (LocalDate, LocalTime) -> Unit, onCancel: () -> Unit) {
    val target = state.target!!
    val context = LocalContext.current
    val now = ZonedDateTime.now(ZoneId.of("Europe/Istanbul"))
    var dateText by rememberSaveable(target.reviewId, target.occurrenceId, target.packageFolder) { mutableStateOf(now.toLocalDate().plusDays(1).toString()) }
    var timeText by rememberSaveable(target.reviewId, target.occurrenceId, target.packageFolder) { mutableStateOf("10:00") }
    val date = LocalDate.parse(dateText)
    val time = LocalTime.parse(timeText)
    val canSubmit = enabled && state.copy(issue = state.issue.takeUnless { it == ReviewIssue.INVALID_TIME }).canDecide
    Text(stringResource(R.string.timezone))
    OutlinedButton(onClick = { DatePickerDialog(context, { _, year, month, day -> dateText = LocalDate.of(year, month + 1, day).toString() }, date.year, date.monthValue - 1, date.dayOfMonth).show() }, enabled = canSubmit, modifier = Modifier.testTag("review-date")) { Text(stringResource(R.string.review_date, dateText)) }
    OutlinedButton(onClick = { TimePickerDialog(context, { _, hour, minute -> timeText = LocalTime.of(hour, minute).toString() }, time.hour, time.minute, true).show() }, enabled = canSubmit, modifier = Modifier.testTag("review-time")) { Text(stringResource(R.string.review_time, timeText)) }
    Button(onClick = { onSubmit(date, time) }, enabled = canSubmit, modifier = Modifier.testTag("review-confirm-reschedule")) { Text(stringResource(R.string.review_confirm_reschedule)) }
    TextButton(onClick = onCancel, enabled = !state.busy) { Text(stringResource(R.string.cancel)) }
}

fun reviewIssueLabel(issue: ReviewIssue) = when (issue) {
    ReviewIssue.STALE -> R.string.review_stale; ReviewIssue.ALREADY_HANDLED -> R.string.review_handled
    ReviewIssue.NOT_FOUND -> R.string.review_not_found; ReviewIssue.UNCERTAIN -> R.string.review_uncertain
    ReviewIssue.INVALID_TIME -> R.string.review_invalid_time; ReviewIssue.PREVIEW -> R.string.review_preview_error
    ReviewIssue.RENDER_FAILED -> R.string.review_render_failed; ReviewIssue.PACKAGE_CHANGED -> R.string.media_changed
    ReviewIssue.INVALID_RESPONSE -> R.string.unknown_error; ReviewIssue.NETWORK -> R.string.network_error
    ReviewIssue.UPLOAD_PENDING -> R.string.review_upload_pending; ReviewIssue.MEDIA_REQUIRED -> R.string.review_media_required
}

@Composable fun ReviewContinuation(state: ReviewState, enabled: Boolean, uploadRows: List<UploadRecord>,
    onContinue: (List<UploadRecord>, Boolean) -> Unit, onAction: (ReviewAction) -> Unit, onRefresh: () -> Unit, onClose: () -> Unit) {
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        SectionHeading(R.string.review_continue_title)
        state.target?.packageFolder?.let { Text(it) }
        Text(stringResource(if (state.continuing) R.string.review_continue_waiting else R.string.review_continue_help))
        state.issue?.let { Text(stringResource(reviewIssueLabel(it)), color = MaterialTheme.colorScheme.error) }
        if (state.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
        val retry = state.issue == ReviewIssue.RENDER_FAILED
        Button(onClick = { onContinue(uploadRows, retry) }, enabled = enabled && !state.busy && !state.continuing &&
            state.issue !in setOf(ReviewIssue.UNCERTAIN, ReviewIssue.PACKAGE_CHANGED, ReviewIssue.ALREADY_HANDLED), modifier = Modifier.testTag("review-continue")) {
            Text(stringResource(if (retry) R.string.retry else R.string.review_continue))
        }
        TextButton(onClick = { onAction(ReviewAction.SKIP) }, enabled = enabled && state.canDecide) { Text(stringResource(R.string.review_skip)) }
        TextButton(onClick = { onAction(ReviewAction.RESCHEDULE) }, enabled = enabled && state.canDecide) { Text(stringResource(R.string.review_reschedule)) }
        TextButton(onClick = onRefresh, enabled = !state.busy) { Text(stringResource(R.string.refresh)) }
        TextButton(onClick = onClose) { Text(stringResource(R.string.close)) }
        HorizontalDivider()
    }
}
