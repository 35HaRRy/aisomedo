package com.dojo.aisomedo.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.*
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.dojo.aisomedo.*
import com.dojo.aisomedo.R
import com.dojo.aisomedo.onboarding.OnboardingScreen
import com.dojo.aisomedo.uploads.UploadRuntime

@Composable fun DojoTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = if (isSystemInDarkTheme()) darkColorScheme() else lightColorScheme(), content = content)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun DojoApp(model: AppViewModel, uploads: UploadRuntime? = null, openUrl: (String) -> Unit) {
    val state by model.state.collectAsStateWithLifecycle()
    DojoTheme {
        BoxWithConstraints(Modifier.fillMaxSize()) {
            val wide = maxWidth >= 600.dp
            val ready = state.phase == Phase.READY
            BackHandler(ready && (state.step != null || state.destination != Destination.DASHBOARD)) {
                if (state.step != null) model.closeSetup() else model.navigate(Destination.DASHBOARD)
            }
            Scaffold(
                topBar = { TopAppBar(title = { Text(stringResource(R.string.app_name)) }) },
                bottomBar = { if (ready && !wide) NavigationBar(Modifier.testTag("navigation-bar")) {
                    Destination.entries.forEach { item -> NavigationBarItem(
                        selected = item == state.destination, onClick = { model.navigate(item) },
                        icon = { NavigationIcon(item) }, label = { Text(stringResource(destinationLabel(item))) }) }
                } },
            ) { padding ->
                Row(Modifier.padding(padding).fillMaxSize()) {
                    if (ready && wide) NavigationRail(Modifier.testTag("navigation-rail")) {
                        Destination.entries.forEach { item -> NavigationRailItem(
                            selected = item == state.destination, onClick = { model.navigate(item) },
                            icon = { NavigationIcon(item) }, label = { Text(stringResource(destinationLabel(item))) }) }
                    }
                    Column(Modifier.weight(1f).fillMaxHeight().imePadding().verticalScroll(rememberScrollState()).padding(24.dp),
                        verticalArrangement = Arrangement.spacedBy(16.dp)) {
                        if (state.busy) LinearProgressIndicator(Modifier.fillMaxWidth().semantics { liveRegion = LiveRegionMode.Polite })
                        state.issue?.let { Text(stringResource(issueLabel(it)), color = MaterialTheme.colorScheme.error,
                            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Assertive }) }
                        if (!ready) StartupScreen(state, model, openUrl)
                        else if (state.step != null) OnboardingScreen(model, openUrl)
                        else when (state.destination) {
                            Destination.DASHBOARD -> DashboardScreen(state.dashboard, state.setup, state.stale, wide, model::refresh, model::openSetup)
                            Destination.PACKAGE -> {
                                Heading(R.string.active_package); PackageSummary(state.dashboard)
                                if (uploads != null) {
                                    val rows by uploads.rows.collectAsStateWithLifecycle()
                                    val issue by uploads.issue.collectAsStateWithLifecycle()
                                    val resolving by uploads.resolvingId.collectAsStateWithLifecycle()
                                    UploadPanel(rows, issue, uploads::enqueue, uploads::pause, uploads::resume, uploads::retry, uploads::dismiss,
                                        resolving, uploads::resolve, uploads::refresh, uploads::preview)
                                    OutlinedButton(onClick = model::refresh, enabled = !state.busy) { Text(stringResource(R.string.refresh)) }
                                }
                            }
                            Destination.ACTIVITY -> { Heading(R.string.activity); Text(stringResource(R.string.activity_later)) }
                            Destination.SETTINGS -> SettingsScreen(state, model)
                        }
                    }
                }
            }
        }
    }
}
@Composable private fun NavigationIcon(item: Destination) {
    Icon(when (item) { Destination.DASHBOARD -> Icons.Default.Home; Destination.PACKAGE -> Icons.Default.Star;
        Destination.ACTIVITY -> Icons.Default.List; Destination.SETTINGS -> Icons.Default.Settings }, contentDescription = null)
}
fun destinationLabel(item: Destination) = when (item) {
    Destination.DASHBOARD -> R.string.dashboard; Destination.PACKAGE -> R.string.package_nav
    Destination.ACTIVITY -> R.string.activity; Destination.SETTINGS -> R.string.settings
}
@Composable fun Heading(label: Int) { Text(stringResource(label), style = MaterialTheme.typography.headlineSmall, modifier = Modifier.semantics { heading() }) }
@Composable fun SectionHeading(label: Int) { Text(stringResource(label), style = MaterialTheme.typography.titleLarge, modifier = Modifier.semantics { heading() }) }
@Composable private fun StartupScreen(state: AppUiState, model: AppViewModel, openUrl: (String) -> Unit) {
    Column(Modifier.widthIn(max = 640.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        when (state.phase) {
            Phase.ADDRESS -> {
                Heading(R.string.server_title); Text(stringResource(R.string.server_help))
                var origin by rememberSaveable { mutableStateOf(state.origin) }
                OutlinedTextField(origin, { origin = it }, label = { Text(stringResource(R.string.server_address)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
                Button(onClick = { model.submitOrigin(origin) }, enabled = !state.busy && origin.isNotBlank()) { Text(stringResource(R.string.connect)) }
            }
            Phase.PAIRING -> {
                Heading(R.string.pair_title); Text(state.origin); Text(stringResource(R.string.pair_help))
                var name by rememberSaveable { mutableStateOf("") }
                var code by remember { mutableStateOf("") }
                OutlinedTextField(name, { name = it }, label = { Text(stringResource(R.string.device_name)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(code, { code = it }, label = { Text(stringResource(R.string.pair_code)) }, visualTransformation = PasswordVisualTransformation(), singleLine = true, modifier = Modifier.fillMaxWidth())
                Button(onClick = { model.pair(code, name); code = "" }, enabled = !state.busy && name.isNotBlank() && code.isNotBlank()) { Text(stringResource(R.string.pair)) }
                TextButton(onClick = model::changeServer, enabled = !state.busy) { Text(stringResource(R.string.change_server)) }
            }
            Phase.UPDATE_REQUIRED -> {
                Heading(R.string.update_title); Text(stringResource(R.string.update_help))
                state.updateUrl?.let { url -> Button(onClick = { openUrl(url) }) { Text(stringResource(R.string.update_download)) } }
                TextButton(onClick = model::refresh, enabled = !state.busy) { Text(stringResource(R.string.retry)) }
                TextButton(onClick = model::changeServer) { Text(stringResource(R.string.change_server)) }
            }
            Phase.CONNECTION_ERROR -> {
                Heading(R.string.connection_title); Text(stringResource(R.string.network_error))
                Button(onClick = model::refresh, enabled = !state.busy) { Text(stringResource(R.string.retry)) }
                TextButton(onClick = model::changeServer) { Text(stringResource(R.string.change_server)) }
            }
            else -> Text(stringResource(R.string.loading))
        }
    }
}
@Composable private fun SettingsScreen(state: AppUiState, model: AppViewModel) {
    var confirm by remember { mutableStateOf(false) }
    Heading(R.string.settings); Text(state.origin)
    state.client?.let { Text(stringResource(R.string.device_identity, it.name, it.id)) }
    state.compat?.let { Text(stringResource(R.string.version_context, BuildConfig.VERSION_CODE, it.androidMinVersionCode, it.androidCurrentVersionCode)) }
    Text(stringResource(if (state.setup?.ready == true) R.string.setup_ready else R.string.setup_incomplete))
    Button(onClick = model::openSetup, enabled = !state.busy) { Text(stringResource(R.string.open_setup)) }
    OutlinedButton(onClick = { confirm = true }, enabled = !state.busy) { Text(stringResource(R.string.change_server)) }
    if (confirm) AlertDialog(onDismissRequest = { confirm = false }, title = { Text(stringResource(R.string.change_server)) },
        text = { Text(stringResource(R.string.change_server_warning)) },
        confirmButton = { TextButton(onClick = { confirm = false; model.changeServer() }) { Text(stringResource(R.string.confirm_change)) } },
        dismissButton = { TextButton(onClick = { confirm = false }) { Text(stringResource(R.string.cancel)) } })
}
fun issueLabel(issue: UiIssue) = when (issue) {
    UiIssue.INVALID_SERVER -> R.string.invalid_server; UiIssue.NETWORK -> R.string.network_error
    UiIssue.INVALID_CODE -> R.string.invalid_code; UiIssue.RATE_LIMIT -> R.string.rate_limit
    UiIssue.INVALID_INPUT -> R.string.invalid_input; UiIssue.PROVIDER_UNAVAILABLE -> R.string.provider_unavailable
    UiIssue.POLICY_MISSING -> R.string.policy_missing; UiIssue.POLICY_CHANGED -> R.string.policy_changed
    UiIssue.STORAGE -> R.string.storage_error; UiIssue.UNKNOWN -> R.string.unknown_error
}
