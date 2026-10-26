package com.dojo.aisomedo.onboarding

import android.app.DatePickerDialog
import android.app.TimePickerDialog
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
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
        val steps = state.setup?.checklist.orEmpty()
        val progress = rememberLazyListState()
        LaunchedEffect(state.step, steps) {
            val index = steps.indexOfFirst { it.key == state.step }
            if (index >= 0) progress.animateScrollToItem(index)
        }
        OutlinedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        LazyRow(state = progress, horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.testTag("setup-steps")) {
            itemsIndexed(steps, key = { _, item -> item.key }) { index, item ->
                val current = state.step == item.key
                Surface(onClick = { model.selectStep(item.key) }, enabled = !state.busy,
                    shape = MaterialTheme.shapes.medium,
                    color = if (current) MaterialTheme.colorScheme.secondaryContainer else MaterialTheme.colorScheme.surface,
                    modifier = Modifier.semantics { selected = current }) {
                    Row(Modifier.padding(12.dp).widthIn(max = 200.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        Surface(shape = CircleShape, color = if (item.complete) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceVariant) {
                            Box(Modifier.size(32.dp), contentAlignment = Alignment.Center) {
                                if (item.complete) Icon(Icons.Default.Check, contentDescription = null, modifier = Modifier.size(20.dp))
                                else Text((index + 1).toString())
                            }
                        }
                        Column {
                            Text(stringResource(stepLabel(item.key)), style = MaterialTheme.typography.labelLarge)
                            Text(stringResource(if (item.complete) R.string.step_complete else if (item.required) R.string.step_required else R.string.step_optional), style = MaterialTheme.typography.labelSmall)
                        }
                    }
                }
            }
        }
        HorizontalDivider()
        if (state.step !in setOf("pairing", "summary") && (!state.networkConnected || !state.authoritative || state.step !in state.configurationFresh)) {
            Text(stringResource(R.string.section_read_only), modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
        }
        if (state.step in state.changedSteps) {
            Text(stringResource(R.string.remote_changed))
            StepHeading(stepLabel(state.step.orEmpty())) {
                OutlinedButton(onClick = { model.reloadStep(state.step.orEmpty()) }, enabled = !state.busy) { Text(stringResource(R.string.reload_step)) }
            }
        }
        when (state.step) {
            "instagram" -> InstagramStep(model, openUrl)
            "logo" -> BrandingSteps(model, false)
            "cards" -> BrandingSteps(model, true)
            "pairing" -> { SectionHeading(R.string.pair_title); state.client?.let { Text(stringResource(R.string.device_identity, it.name, it.id)) } }
            "schedule" -> ScheduleStep(state, model)
            "consent" -> {
                ConsentStep(state.consent, state.busy, { version -> model.acknowledgeConsent(true); model.acceptConsent(version) }, canMutate = state.canConfigure("consent"), actions = {
                    TextButton(onClick = { model.reloadStep("consent") }, enabled = !state.busy) { Text(stringResource(R.string.retry)) }
                })
            }
            "caption_template" -> CaptionStep(state, model)
            "summary" -> {
                SectionHeading(R.string.setup_summary)
                Text(stringResource(if (state.setup?.ready == true) R.string.setup_ready else R.string.setup_incomplete))
            }
            else -> Text(stringResource(R.string.step_not_loaded))
        }
        HorizontalDivider()
        SetupNavigation(state.setup?.ready == true, state.canMutate, state.busy, state.step != "summary", model::nextStep, model::finishSetup, model::closeSetup)
        }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable internal fun StepHeading(label: Int, leading: @Composable () -> Unit = {}, actions: @Composable () -> Unit = {}) {
    FlowRow(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        leading()
        Text(stringResource(label), style = MaterialTheme.typography.titleMedium, modifier = Modifier.align(Alignment.CenterVertically).semantics { heading() })
        actions()
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable internal fun SetupNavigation(ready: Boolean, canMutate: Boolean, busy: Boolean, showNext: Boolean,
    onNext: () -> Unit, onFinish: () -> Unit, onLater: () -> Unit) {
    FlowRow(Modifier.fillMaxWidth().testTag("setup-actions"), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (showNext) TextButton(onClick = onNext, enabled = !busy) { Text(stringResource(R.string.next_step)) }
        if (ready) Button(onClick = onFinish, enabled = canMutate && !busy) { Text(stringResource(R.string.finish_setup)) }
        else TextButton(onClick = onLater) { Text(stringResource(R.string.leave_setup)) }
    }
}

@Composable fun CaptionStep(state: AppUiState, model: AppViewModel) {
    val text = state.drafts["caption"].orEmpty()
    StepHeading(R.string.caption_template) {
        Button(onClick = { model.saveCaption(text) }, enabled = state.canConfigure("caption_template") && text.isNotBlank()) { Text(stringResource(R.string.save)) }
    }
    OutlinedTextField(text, { model.setDraft("caption", it, "caption_template") }, label = { Text(stringResource(R.string.caption_template)) }, modifier = Modifier.fillMaxWidth(), minLines = 3,
        enabled = state.networkConnected && state.authoritative && "caption_template" in state.configurationFresh)
}

@Composable fun ScheduleStep(state: AppUiState, model: AppViewModel) {
    val context = LocalContext.current
    val date = state.drafts["date"].orEmpty()
    val time = state.drafts["time"].orEmpty()
    val enabled = state.drafts["enabled"] != "false"
    val access = state.canConfigure("schedule")
    StepHeading(R.string.schedule) {
        Button(onClick = { model.savePlan(date, time, enabled) }, enabled = access && date.isNotBlank() && time.isNotBlank()) { Text(stringResource(R.string.save)) }
    }
    Text(stringResource(R.string.plan_help))
    OutlinedButton(onClick = {
        val initial = runCatching { LocalDate.parse(date) }.getOrDefault(LocalDate.now(ZoneId.of("Europe/Istanbul")))
        DatePickerDialog(context, { _, year, month, day -> if (model.state.value.canConfigure("schedule")) model.setDraft("date", LocalDate.of(year, month + 1, day).toString(), "schedule") }, initial.year, initial.monthValue - 1, initial.dayOfMonth).show()
    }, enabled = access, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.anchor_date, date.ifBlank { stringResource(R.string.choose) })) }
    OutlinedButton(onClick = {
        val initial = runCatching { LocalTime.parse(time) }.getOrDefault(LocalTime.of(18, 0))
        TimePickerDialog(context, { _, hour, minute -> if (model.state.value.canConfigure("schedule")) model.setDraft("time", String.format(Locale.ROOT, "%02d:%02d", hour, minute), "schedule") }, initial.hour, initial.minute, true).show()
    }, enabled = access, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.anchor_time, time.ifBlank { stringResource(R.string.choose) })) }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
        Checkbox(enabled, { model.setDraft("enabled", it.toString(), "schedule") }, enabled = access,
            modifier = Modifier.semantics { contentDescription = context.getString(R.string.plan_enabled) })
        Text(stringResource(R.string.plan_enabled), Modifier.weight(1f))
    }
}

@Composable fun ConsentStep(policy: ConsentOut?, busy: Boolean, onAccept: (Int) -> Unit) {
    ConsentStep(policy, busy, onAccept, canMutate = true)
}

@Composable fun ConsentStep(policy: ConsentOut?, busy: Boolean, onAccept: (Int) -> Unit, canMutate: Boolean, readOnly: Boolean = false, actions: @Composable () -> Unit = {}) {
    var acknowledged by remember(policy) { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
        StepHeading(R.string.consent) {
            if (policy != null && policy.acceptedAt == null && !readOnly) {
                Button(onClick = { onAccept(policy.version); acknowledged = false }, enabled = canMutate && !busy && acknowledged) { Text(stringResource(R.string.accept_policy)) }
            }
            actions()
        }
        if (policy == null) Text(stringResource(R.string.policy_missing))
        else {
            Text(stringResource(R.string.policy_version, policy.version))
            Text(policy.text)
            if (policy.acceptedAt != null) Text(stringResource(R.string.policy_accepted, formattedTime(policy.acceptedAt)))
            else if (readOnly) Text(stringResource(R.string.policy_not_accepted))
            else {
                val acknowledgement = stringResource(R.string.policy_acknowledgement)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(acknowledged, { acknowledged = it }, enabled = canMutate && !busy,
                        modifier = Modifier.testTag("consent-acknowledgement").semantics { contentDescription = acknowledgement })
                    Text(acknowledgement)
                }
            }
        }
    }
}
fun stepLabel(key: String) = when (key) {
    "pairing" -> R.string.pair_title; "instagram" -> R.string.instagram; "schedule" -> R.string.schedule
    "consent" -> R.string.consent; "logo" -> R.string.logo; "caption_template" -> R.string.caption_template
    "cards" -> R.string.cards; "summary" -> R.string.setup_summary; else -> R.string.unknown_step
}
