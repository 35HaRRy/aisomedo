package com.dojo.aisomedo.onboarding

import android.app.DatePickerDialog
import android.app.TimePickerDialog
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.*
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.dojo.aisomedo.AppViewModel
import com.dojo.aisomedo.AppUiState
import com.dojo.aisomedo.R
import com.dojo.aisomedo.api.ConsentOut
import com.dojo.aisomedo.ui.*
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZoneId
import java.util.Locale

@Composable fun OnboardingScreen(model: AppViewModel, openUrl: (String) -> Unit) {
    val state by model.state.collectAsStateWithLifecycle()
    Column(Modifier.widthIn(max = 640.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Heading(R.string.setup)
        Text(stringResource(R.string.setup_progress, state.setup?.checklist?.count { it.complete } ?: 0, state.setup?.checklist?.size ?: 0))
        SectionHeading(stepLabel(state.step.orEmpty()))
        if (state.step in state.changedSteps) {
            Text(stringResource(R.string.remote_changed))
            OutlinedButton(onClick = { model.reloadStep(state.step.orEmpty()) }, enabled = !state.busy) { Text(stringResource(R.string.reload_step)) }
        }
        when (state.step) {
            "instagram" -> InstagramStep(model, openUrl)
            "pairing" -> state.client?.let { Text(stringResource(R.string.device_identity, it.name, it.id)) }
            "schedule" -> ScheduleStep(state, model)
            "consent" -> {
                ConsentStep(state.consent, state.busy) { version -> model.acknowledgeConsent(true); model.acceptConsent(version) }
                TextButton(onClick = { model.reloadStep("consent") }, enabled = !state.busy) { Text(stringResource(R.string.retry)) }
            }
            "caption_template" -> {
                val text = state.drafts["caption"].orEmpty()
                OutlinedTextField(text, { model.setDraft("caption", it, "caption_template") }, label = { Text(stringResource(R.string.caption_template)) }, modifier = Modifier.fillMaxWidth(), minLines = 3)
                Button(onClick = { model.saveCaption(text) }, enabled = !state.busy && text.isNotBlank()) { Text(stringResource(R.string.save)) }
            }
            "summary" -> {
                Text(stringResource(if (state.setup?.ready == true) R.string.setup_ready else R.string.setup_incomplete))
                Button(onClick = model::finishSetup, enabled = !state.busy && state.setup?.ready == true) { Text(stringResource(R.string.finish_setup)) }
            }
            else -> Text(stringResource(R.string.step_not_loaded))
        }
        if (state.step != "summary") TextButton(onClick = model::nextStep, enabled = !state.busy) { Text(stringResource(R.string.next_step)) }
        TextButton(onClick = model::closeSetup) { Text(stringResource(R.string.leave_setup)) }
        HorizontalDivider()
        state.setup?.checklist?.forEach { item ->
            TextButton(onClick = { model.selectStep(item.key) }, enabled = !state.busy,
                modifier = Modifier.fillMaxWidth().semantics { selected = state.step == item.key }) {
                Text(stringResource(stepLabel(item.key)), Modifier.weight(1f))
                Text(stringResource(if (item.complete) R.string.step_complete else if (item.required) R.string.step_required else R.string.step_optional))
            }
        }
    }
}

@Composable private fun ScheduleStep(state: AppUiState, model: AppViewModel) {
    val context = LocalContext.current
    val date = state.drafts["date"].orEmpty()
    val time = state.drafts["time"].orEmpty()
    val enabled = state.drafts["enabled"] != "false"
    Text(stringResource(R.string.plan_help))
    OutlinedButton(onClick = {
        val initial = runCatching { LocalDate.parse(date) }.getOrDefault(LocalDate.now(ZoneId.of("Europe/Istanbul")))
        DatePickerDialog(context, { _, year, month, day -> model.setDraft("date", LocalDate.of(year, month + 1, day).toString(), "schedule") }, initial.year, initial.monthValue - 1, initial.dayOfMonth).show()
    }, enabled = !state.busy) { Text(stringResource(R.string.anchor_date, date.ifBlank { stringResource(R.string.choose) })) }
    OutlinedButton(onClick = {
        val initial = runCatching { LocalTime.parse(time) }.getOrDefault(LocalTime.of(18, 0))
        TimePickerDialog(context, { _, hour, minute -> model.setDraft("time", String.format(Locale.ROOT, "%02d:%02d", hour, minute), "schedule") }, initial.hour, initial.minute, true).show()
    }, enabled = !state.busy) { Text(stringResource(R.string.anchor_time, time.ifBlank { stringResource(R.string.choose) })) }
    Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
        Text(stringResource(R.string.plan_enabled), Modifier.weight(1f))
        Switch(enabled, { model.setDraft("enabled", it.toString(), "schedule") }, enabled = !state.busy,
            modifier = Modifier.semantics { contentDescription = context.getString(R.string.plan_enabled) })
    }
    Button(onClick = { model.savePlan(date, time, enabled) }, enabled = !state.busy && date.isNotBlank() && time.isNotBlank()) { Text(stringResource(R.string.save)) }
}

@Composable fun ConsentStep(policy: ConsentOut?, busy: Boolean, onAccept: (Int) -> Unit) {
    var acknowledged by remember(policy) { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
        if (policy == null) Text(stringResource(R.string.policy_missing))
        else {
            Text(stringResource(R.string.policy_version, policy.version))
            Text(policy.text)
            if (policy.acceptedAt != null) Text(stringResource(R.string.policy_accepted, formattedTime(policy.acceptedAt)))
            else {
                val acknowledgement = stringResource(R.string.policy_acknowledgement)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Checkbox(acknowledged, { acknowledged = it }, enabled = !busy,
                        modifier = Modifier.testTag("consent-acknowledgement").semantics { contentDescription = acknowledgement })
                    Text(acknowledgement)
                }
                Button(onClick = { onAccept(policy.version); acknowledged = false }, enabled = !busy && acknowledged) { Text(stringResource(R.string.accept_policy)) }
            }
        }
    }
}
fun stepLabel(key: String) = when (key) {
    "pairing" -> R.string.pair_title; "instagram" -> R.string.instagram; "schedule" -> R.string.schedule
    "consent" -> R.string.consent; "logo" -> R.string.logo; "caption_template" -> R.string.caption_template
    "cards" -> R.string.cards; "summary" -> R.string.setup_summary; else -> R.string.unknown_step
}
