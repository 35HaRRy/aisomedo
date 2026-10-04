package com.dojo.aisomedo.ui

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.dojo.aisomedo.R
import com.dojo.aisomedo.api.*
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

@Composable fun DashboardScreen(dashboard: DashboardOut?, setup: SetupOut?, stale: Boolean, wide: Boolean, onRefresh: () -> Unit, onSetup: () -> Unit) {
    Heading(R.string.dashboard)
    TextButton(onClick = onRefresh) { Text(stringResource(R.string.refresh)) }
    if (dashboard == null) { Text(stringResource(R.string.dashboard_unavailable)); return }
    if (stale) Text(stringResource(R.string.stale, formattedTime(dashboard.generatedAt)))
    SectionHeading(R.string.pending)
    if (dashboard.pendingActions.isEmpty()) Text(stringResource(R.string.no_pending))
    dashboard.pendingActions.forEach { action ->
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(stringResource(statusLabel(action.state)), style = MaterialTheme.typography.titleMedium)
            Text(formattedTime(action.dueAt)); action.packageFolder?.let { Text(it) }
            Text(stringResource(R.string.pending_read_only)); HorizontalDivider()
        }
    }
    if (wide) Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(32.dp)) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(16.dp)) { PublishingSummary(dashboard) }
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(16.dp)) { HealthSummary(dashboard) }
    } else { PublishingSummary(dashboard); HealthSummary(dashboard) }
    HorizontalDivider()
    Text(stringResource(if (setup?.ready == true) R.string.setup_ready else R.string.setup_incomplete))
    Button(onClick = onSetup) { Text(stringResource(R.string.open_setup)) }
}
@Composable fun PackageSummary(dashboard: DashboardOut?) {
    val value = dashboard?.`package`
    Text(value?.folderName ?: stringResource(if (dashboard == null) R.string.dashboard_unavailable else R.string.no_package), style = MaterialTheme.typography.titleMedium)
    if (value != null) { Text(stringResource(statusLabel(value.status))); Text(formattedTime(value.createdAt)) }
}
@Composable private fun PublishingSummary(value: DashboardOut) {
    SectionHeading(R.string.active_package); PackageSummary(value)
    SectionHeading(R.string.next_slot)
    Text(value.nextSlot?.let { formattedTime(it.dueAt) } ?: stringResource(R.string.no_slot), style = MaterialTheme.typography.titleMedium)
    value.nextSlot?.let { Text(stringResource(statusLabel(it.kind))) }; Text(stringResource(R.string.timezone))
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
    "review_ready" -> R.string.review_ready; "empty_package" -> R.string.empty_package; "preparing" -> R.string.preparing
    "healthy", "connected" -> R.string.healthy; "unhealthy" -> R.string.unhealthy; "not_connected" -> R.string.not_connected
    "expired" -> R.string.expired; "expiring" -> R.string.expiring; "revoked" -> R.string.revoked
    "idle" -> R.string.idle; "busy" -> R.string.busy; "stopped" -> R.string.stopped
    "active" -> R.string.active; "completed" -> R.string.completed; "regular" -> R.string.regular; "one_off" -> R.string.one_off
    else -> R.string.unknown_status
}
