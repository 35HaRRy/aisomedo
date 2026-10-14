package com.dojo.aisomedo.ui

import android.app.TimePickerDialog
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.*
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.dojo.aisomedo.*
import com.dojo.aisomedo.R
import com.dojo.aisomedo.onboarding.*
import java.time.LocalTime
import java.util.Locale

@Composable fun SettingsScreen(state: AppUiState, model: AppViewModel, openUrl: (String) -> Unit) {
    var confirm by remember { mutableStateOf(false) }
    Heading(R.string.settings)
    Text(state.origin)
    state.client?.let { Text(stringResource(R.string.device_identity, it.name, it.id)) }
    state.compat?.let { Text(stringResource(R.string.version_context, BuildConfig.VERSION_CODE, it.androidMinVersionCode, it.androidCurrentVersionCode)) }
    Text(stringResource(if (state.setup?.ready == true) R.string.setup_ready else R.string.setup_incomplete))
    Button(onClick = model::openSetup, enabled = !state.busy) { Text(stringResource(R.string.open_setup)) }
    OutlinedButton(onClick = model::refresh, enabled = !state.busy && state.networkConnected) { Text(stringResource(R.string.refresh)) }
    SettingsSection("schedule", R.string.schedule, state, model) { ScheduleStep(state, model) }
    SettingsSection("reminders", R.string.reminders, state, model) { ReminderSettings(state, model) }
    SettingsSection("logo", R.string.logo, state, model) { BrandingSteps(model, false, onboarding = false) }
    SettingsSection("caption_template", R.string.caption_template, state, model) { CaptionStep(state, model) }
    SettingsSection("cards", R.string.cards, state, model) { BrandingSteps(model, true, onboarding = false) }
    SettingsSection("instagram", R.string.instagram, state, model) { InstagramStep(model, openUrl) }
    SettingsSection("consent", R.string.consent, state, model) {
        ConsentStep(state.consent, state.busy, {}, canMutate = false, readOnly = true)
    }
    HorizontalDivider()
    OutlinedButton(onClick = { confirm = true }, enabled = !state.busy) { Text(stringResource(R.string.change_server)) }
    if (confirm) AlertDialog(onDismissRequest = { confirm = false }, title = { Text(stringResource(R.string.change_server)) },
        text = { Text(stringResource(R.string.change_server_warning)) },
        confirmButton = { TextButton(onClick = { confirm = false; model.changeServer() }) { Text(stringResource(R.string.confirm_change)) } },
        dismissButton = { TextButton(onClick = { confirm = false }) { Text(stringResource(R.string.cancel)) } })
}

@Composable private fun SettingsSection(key: String, title: Int, state: AppUiState, model: AppViewModel, content: @Composable () -> Unit) {
    HorizontalDivider()
    Column(Modifier.fillMaxWidth().widthIn(max = 640.dp).testTag("settings-$key"), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        SectionHeading(title)
        if (!state.networkConnected || !state.authoritative || key !in state.configurationFresh) {
            Text(stringResource(R.string.section_read_only), modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
        }
        if (key in state.changedSteps) {
            Text(stringResource(R.string.remote_changed), modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
            OutlinedButton(onClick = { model.reloadStep(key) }, enabled = !state.busy && state.networkConnected) { Text(stringResource(R.string.reload_step)) }
        }
        content()
    }
}

@Composable private fun ReminderSettings(state: AppUiState, model: AppViewModel) {
    val interval = state.drafts["reminder_interval"].orEmpty()
    val access = state.canConfigure("reminders")
    Text(stringResource(R.string.reminder_help))
    Text(stringResource(R.string.timezone), style = MaterialTheme.typography.bodySmall)
    OutlinedTextField(interval, { model.setDraft("reminder_interval", it, "reminders") },
        label = { Text(stringResource(R.string.reminder_interval)) }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
        singleLine = true, enabled = access, modifier = Modifier.fillMaxWidth().testTag("reminder-interval"))
    ReminderTime(state, model, "reminder_start", R.string.reminder_start)
    ReminderTime(state, model, "reminder_end", R.string.reminder_end)
    Button(onClick = { model.saveReminders(interval, state.drafts["reminder_start"].orEmpty(), state.drafts["reminder_end"].orEmpty()) },
        enabled = access, modifier = Modifier.testTag("reminder-save")) { Text(stringResource(R.string.save_reminders)) }
}

@Composable private fun ReminderTime(state: AppUiState, model: AppViewModel, key: String, label: Int) {
    val context = LocalContext.current
    val value = state.drafts[key].orEmpty()
    OutlinedButton(onClick = {
        val initial = runCatching { LocalTime.parse(value) }.getOrDefault(LocalTime.NOON)
        TimePickerDialog(context, { _, hour, minute ->
            if (model.state.value.canConfigure("reminders")) model.setDraft(key, String.format(Locale.ROOT, "%02d:%02d", hour, minute), "reminders")
        }, initial.hour, initial.minute, true).show()
    }, enabled = state.canConfigure("reminders"), modifier = Modifier.testTag(key)) {
        Text(stringResource(label, value.ifBlank { stringResource(R.string.choose) }))
    }
}
