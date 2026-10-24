package com.dojo.aisomedo.ui

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import android.app.DatePickerDialog
import android.app.TimePickerDialog
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.dojo.aisomedo.R
import com.dojo.aisomedo.api.*
import com.dojo.aisomedo.reviews.ReviewAction
import com.dojo.aisomedo.reviews.ReviewIssue
import com.dojo.aisomedo.reviews.futureIstanbulInstant
import java.time.Instant
import java.time.LocalDate
import java.time.LocalTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

@Composable fun DashboardScreen(dashboard: DashboardOut?, setup: SetupOut?, stale: Boolean, wide: Boolean, onRefresh: () -> Unit, onSetup: () -> Unit, onPending: (DashboardActionOut, ReviewAction) -> Unit = { _, _ -> }, canMutate: Boolean = true, onChangeOneoffDate: (DashboardSlotOut, LocalDate, LocalTime) -> Unit = { _, _, _ -> }, onDecideOneoff: (DashboardSlotOut, Boolean) -> Unit = { _, _ -> }, oneoffDecision: OneoffDecisionOut? = null, oneoffDecisionIssue: ReviewIssue? = null) {
    Heading(R.string.dashboard)
    TextButton(onClick = onRefresh) { Text(stringResource(R.string.refresh)) }
    if (dashboard == null) { Text(stringResource(R.string.dashboard_unavailable)); return }
    if (stale) Text(stringResource(R.string.stale, formattedTime(dashboard.generatedAt)))
    oneoffDecision?.let { Text(stringResource(if (it.status == "skipped") R.string.review_skipped else R.string.review_continue_waiting)) }
    oneoffDecisionIssue?.let { Text(stringResource(reviewIssueLabel(it))) }
    PendingPanel(dashboard, canMutate && !stale, onPending)
    if (wide) Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(32.dp)) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(16.dp)) { PublishingSummary(dashboard, canMutate && !stale, onChangeOneoffDate, onDecideOneoff, oneoffDecision) }
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(16.dp)) { HealthSummary(dashboard) }
    } else { PublishingSummary(dashboard, canMutate && !stale, onChangeOneoffDate, onDecideOneoff, oneoffDecision); HealthSummary(dashboard) }
    HorizontalDivider()
    Text(stringResource(if (setup?.ready == true) R.string.setup_ready else R.string.setup_incomplete))
    Button(onClick = onSetup) { Text(stringResource(R.string.open_setup)) }
}
@Composable fun ApprovalInbox(dashboard: DashboardOut?, stale: Boolean, onRefresh: () -> Unit, onPending: (DashboardActionOut, ReviewAction) -> Unit, canMutate: Boolean = true) {
    Heading(R.string.approval_inbox)
    TextButton(onClick = onRefresh) { Text(stringResource(R.string.refresh)) }
    if (dashboard == null) { Text(stringResource(R.string.dashboard_unavailable)); return }
    if (stale) Text(stringResource(R.string.stale, formattedTime(dashboard.generatedAt)))
    PendingRows(dashboard, canMutate && !stale, onPending)
}
@Composable private fun PendingRows(dashboard: DashboardOut, enabled: Boolean, onPending: (DashboardActionOut, ReviewAction) -> Unit) {
    if (dashboard.pendingActions.isEmpty()) Text(stringResource(R.string.no_pending))
    dashboard.pendingActions.forEach { action ->
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(stringResource(statusLabel(action.reviewStatus ?: action.state)), style = MaterialTheme.typography.titleMedium)
            Text(formattedTime(action.dueAt)); action.packageFolder?.let { Text(it) }
            Button(onClick = { onPending(action, if (action.state == "empty_package") ReviewAction.UPLOAD else ReviewAction.REVIEW) }, enabled = enabled) { Text(stringResource(if (action.state == "empty_package") R.string.open_package else R.string.review_open)) }
            if (action.state == "empty_package" && action.packageFolder != null) {
                TextButton(onClick = { onPending(action, ReviewAction.SKIP) }, enabled = enabled) { Text(stringResource(R.string.review_skip)) }
                TextButton(onClick = { onPending(action, ReviewAction.RESCHEDULE) }, enabled = enabled) { Text(stringResource(R.string.review_reschedule)) }
            }
            HorizontalDivider()
        }
    }
}
@Composable fun PackageSummary(dashboard: DashboardOut?) {
    val value = dashboard?.`package`
    Text(value?.folderName ?: stringResource(if (dashboard == null) R.string.dashboard_unavailable else R.string.no_package), style = MaterialTheme.typography.titleMedium)
    if (value != null) { Text(stringResource(statusLabel(value.status))); Text(formattedTime(value.createdAt)) }
}
@Composable private fun PublishingSummary(value: DashboardOut, enabled: Boolean, onChange: (DashboardSlotOut, LocalDate, LocalTime) -> Unit,
    onDecide: (DashboardSlotOut, Boolean) -> Unit, decision: OneoffDecisionOut?) {
    SectionHeading(R.string.active_package); PackageSummary(value)
    SectionHeading(R.string.next_slot)
    val slots = value.nextSlots ?: listOfNotNull(value.nextSlot)
    val regular = slots.filter { it.kind == "regular" && OffsetDateTime.parse(it.dueAt).toInstant() > Instant.now() }
        .minByOrNull { OffsetDateTime.parse(it.dueAt).toInstant() }?.dueAt
    if (slots.isEmpty()) Text(stringResource(R.string.no_slot), style = MaterialTheme.typography.titleMedium)
    slots.forEach { slot ->
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(formattedTime(slot.dueAt), style = MaterialTheme.typography.titleMedium)
            Text(stringResource(statusLabel(slot.kind)))
            if (slot.kind == "oneoff" && slot.occurrenceId != null && OffsetDateTime.parse(slot.dueAt).toInstant() > Instant.now()) {
                val canDecide = enabled && decision?.status != "pending" && decision?.occurrenceId != slot.occurrenceId
                key(slot.occurrenceId, slot.dueAt) {
                    var confirmSkip by rememberSaveable { mutableStateOf(false) }
                    Button(onClick = { onDecide(slot, false) }, enabled = canDecide) { Text(stringResource(R.string.oneoff_review)) }
                    TextButton(onClick = { confirmSkip = true }, enabled = canDecide) { Text(stringResource(R.string.review_skip)) }
                    if (confirmSkip) {
                        Text(stringResource(R.string.review_skip_warning))
                        Button(onClick = { confirmSkip = false; onDecide(slot, true) }, enabled = canDecide) { Text(stringResource(R.string.review_confirm_skip)) }
                        TextButton(onClick = { confirmSkip = false }) { Text(stringResource(R.string.cancel)) }
                    }
                    OneoffDateForm(slot, regular, canDecide, onChange)
                }
            }
        }
    }
    Text(stringResource(R.string.timezone))
}
@Composable fun PendingPanel(dashboard: DashboardOut?, enabled: Boolean, onPending: (DashboardActionOut, ReviewAction) -> Unit) {
    if (dashboard == null || dashboard.pendingActions.isEmpty()) return
    CollapsiblePanel(stringResource(R.string.pending)) { PendingRows(dashboard, enabled, onPending) }
}
@Composable private fun OneoffDateForm(slot: DashboardSlotOut, regular: String?, enabled: Boolean, onChange: (DashboardSlotOut, LocalDate, LocalTime) -> Unit) {
    val context = LocalContext.current
    val initial = OffsetDateTime.parse(slot.dueAt).atZoneSameInstant(ZoneId.of("Europe/Istanbul"))
    var editing by rememberSaveable { mutableStateOf(false) }
    var dateText by rememberSaveable { mutableStateOf(initial.toLocalDate().toString()) }
    var timeText by rememberSaveable { mutableStateOf(initial.toLocalTime().withSecond(0).withNano(0).toString()) }
    val date = LocalDate.parse(dateText); val time = LocalTime.parse(timeText)
    val access by rememberUpdatedState(enabled)
    if (!editing) TextButton(onClick = { editing = true }, enabled = enabled) { Text(stringResource(R.string.oneoff_change_date)) }
    else {
        Text(stringResource(R.string.oneoff_date_help))
        regular?.let { Text(stringResource(R.string.review_next_regular, formattedTime(it))) }
        OutlinedButton(onClick = { DatePickerDialog(context, { _, year, month, day -> if (access) dateText = LocalDate.of(year, month + 1, day).toString() }, date.year, date.monthValue - 1, date.dayOfMonth).show() }, enabled = enabled, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.review_date, dateText)) }
        OutlinedButton(onClick = { TimePickerDialog(context, { _, hour, minute -> if (access) timeText = LocalTime.of(hour, minute).toString() }, time.hour, time.minute, true).show() }, enabled = enabled, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.review_time, timeText)) }
        Button(onClick = { onChange(slot, date, time); editing = false }, enabled = enabled && futureIstanbulInstant(date, time, Instant.now(), regular) != null) { Text(stringResource(R.string.save)) }
        TextButton(onClick = { editing = false }, enabled = enabled) { Text(stringResource(R.string.cancel)) }
    }
}
@Composable private fun HealthSummary(value: DashboardOut) {
    SectionHeading(R.string.instagram); Text(value.instagram.username ?: stringResource(R.string.no_account))
    Text(stringResource(statusLabel(value.instagram.health))); SectionHeading(R.string.worker)
    Text(stringResource(statusLabel(value.worker.status))); value.worker.phase?.let { Text(stringResource(statusLabel(it))) }
}
@Composable fun formattedTime(raw: String): String = try {
    OffsetDateTime.parse(raw).atZoneSameInstant(ZoneId.of("Europe/Istanbul")).format(DateTimeFormatter.ofPattern("d MMM yyyy HH:mm", Locale.forLanguageTag("tr-TR")))
} catch (_: Exception) { stringResource(R.string.unknown_time) }
fun statusLabel(value: String) = when (value) {
    "publishing" -> R.string.review_publishing; "failed" -> R.string.review_failed; "uncertain" -> R.string.review_status_uncertain
    "review_ready" -> R.string.review_ready; "empty_package" -> R.string.empty_package; "preparing" -> R.string.preparing
    "healthy", "connected" -> R.string.healthy; "unhealthy" -> R.string.unhealthy; "not_connected" -> R.string.not_connected
    "expired" -> R.string.expired; "expiring" -> R.string.expiring; "revoked" -> R.string.revoked
    "refresh_due" -> R.string.refresh_due; "reconnect_required" -> R.string.reconnect_required
    "idle" -> R.string.idle; "busy" -> R.string.busy; "stopped" -> R.string.stopped
    "active" -> R.string.active; "completed" -> R.string.completed; "regular" -> R.string.regular; "manual" -> R.string.manual; "one_off", "oneoff" -> R.string.one_off
    else -> R.string.unknown_status
}
