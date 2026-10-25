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
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.layout.boundsInRoot
import androidx.compose.ui.layout.onGloballyPositioned
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
import com.dojo.aisomedo.reviews.*
import com.dojo.aisomedo.notifications.*

@Composable fun DojoTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = if (isSystemInDarkTheme()) darkColorScheme() else lightColorScheme(), content = content)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun DojoApp(model: AppViewModel, uploads: UploadRuntime? = null, push: PushRuntime? = null,
    onNotificationPermission: () -> Unit = {}, onNotificationSettings: () -> Unit = {}, openUrl: (String) -> Unit) {
    val state by model.state.collectAsStateWithLifecycle()
    val onPending: (com.dojo.aisomedo.api.DashboardActionOut, ReviewAction) -> Unit = { pending, action ->
        if (action == ReviewAction.UPLOAD) model.navigate(Destination.PACKAGE)
        else if (pending.reviewId != null) model.openReview(ReviewTarget(reviewId = pending.reviewId, packageFolder = pending.packageFolder, expectedVersion = pending.version, action = action))
        else if (pending.packageFolder != null) model.openReview(ReviewTarget(occurrenceId = pending.occurrenceId, packageFolder = pending.packageFolder, action = action))
        else model.navigate(Destination.PACKAGE)
    }
    DojoTheme {
        BoxWithConstraints(Modifier.fillMaxSize()) {
            val wide = maxWidth >= 600.dp
            val scroll = rememberScrollState()
            var viewport by remember { mutableStateOf(Rect.Zero) }
            val ready = state.phase == Phase.READY
            BackHandler(ready && (state.review.target != null || state.step != null || state.destination != Destination.DASHBOARD)) {
                if (state.review.target != null) model.closeReview()
                else if (state.step != null) model.closeSetup() else model.navigate(Destination.DASHBOARD)
            }
            Scaffold(
                topBar = { TopAppBar(title = { Text(stringResource(R.string.app_name)) }) },
                bottomBar = { if (ready && !wide) NavigationBar(Modifier.testTag("navigation-bar")) {
                    Destination.entries.forEach { item -> NavigationBarItem(
                        selected = item == state.destination, onClick = { if (state.review.target != null) model.closeReview(); model.navigate(item) },
                        icon = { NavigationIcon(item) }, label = { Text(stringResource(destinationLabel(item))) }) }
                } },
            ) { padding ->
                Row(Modifier.padding(padding).fillMaxSize()) {
                    if (ready && wide) NavigationRail(Modifier.testTag("navigation-rail")) {
                        Destination.entries.forEach { item -> NavigationRailItem(
                            selected = item == state.destination, onClick = { if (state.review.target != null) model.closeReview(); model.navigate(item) },
                            icon = { NavigationIcon(item) }, label = { Text(stringResource(destinationLabel(item))) }) }
                    }
                    Column(Modifier.weight(1f).fillMaxHeight().imePadding().onGloballyPositioned { viewport = it.boundsInRoot() }.verticalScroll(scroll).padding(24.dp),
                        verticalArrangement = Arrangement.spacedBy(16.dp)) {
                        if (state.busy) LinearProgressIndicator(Modifier.fillMaxWidth().semantics { liveRegion = LiveRegionMode.Polite })
                        state.issue?.let { Text(stringResource(issueLabel(it)), color = MaterialTheme.colorScheme.error,
                            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Assertive }) }
                        if (state.showConnectionNotice) Surface(
                            color = MaterialTheme.colorScheme.secondaryContainer, shape = MaterialTheme.shapes.medium,
                            modifier = Modifier.fillMaxWidth().testTag("offline-notice")) {
                            Column(Modifier.padding(16.dp)) {
                                Text(stringResource(if (state.networkConnected) R.string.backend_unavailable_notice else R.string.offline_notice),
                                    modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
                                OutlinedButton(onClick = model::refresh, enabled = !state.busy && state.networkConnected) { Text(stringResource(R.string.refresh)) }
                            }
                        }
                        if (!ready) StartupScreen(state, model, openUrl)
                        else if (state.review.target != null && state.review.target?.action != ReviewAction.UPLOAD) ReviewScreen(state.review, state.canMutate && !state.stale,
                            model::requestReviewAction, model::approveReview, model::skipReview, model::rescheduleReview,
                            model::refreshReview, model::closeReview, preview = { detail ->
                                if (state.networkConnected && state.authoritative) ReviewPreview(detail, model::downloadReviewPreview, model::markReviewPreviewReady)
                                else Text(stringResource(R.string.offline_media), modifier = Modifier.testTag("review-offline-preview"))
                            }, onEdit = { model.closeReview(); model.navigate(Destination.PACKAGE) })
                        else if (state.step != null) OnboardingScreen(model, openUrl)
                        else when (state.destination) {
                            Destination.DASHBOARD -> DashboardScreen(state.dashboard, state.setup, state.stale, wide, model::refresh, model::openSetup, onPending,
                                canMutate = state.canMutate && state.issue == null, onChangeOneoffDate = model::changeOneoffDate,
                                onDecideOneoff = model::decideOneoff, oneoffDecision = state.oneoffDecision, oneoffDecisionIssue = state.oneoffDecisionIssue)
                            Destination.PACKAGE -> {
                                Heading(R.string.active_package)
                                CollapsiblePanel(stringResource(R.string.package_summary)) {
                                    PackageSummary(state.dashboard)
                                    LastFetchedAt(state.dashboardFetchedAt, "package-fetched-at")
                                    LastFetchedAt(state.editorFetchedAt, "editor-fetched-at")
                                }
                                if (state.editor.snapshot == null && state.editor.storedDraft == null && state.editor.persistenceIssue == null && state.editorFetchedAt == null && (state.dashboardFetchedAt == null || state.dashboard?.`package` != null)) {
                                    Text(stringResource(R.string.cache_unavailable))
                                    OutlinedButton(onClick = model::refresh, enabled = !state.busy && state.networkConnected) { Text(stringResource(R.string.refresh)) }
                                } else MediaEditorPanel(state.editor, state.busy, scroll, viewport, model::refreshEditor, model::reorderMedia,
                                    model::removeMedia, model::restoreMedia, model::editRanges, model::saveMedia, model::discardMedia,
                                    canMutate = state.canEditMedia, onPreview = model::downloadMediaPreview,
                                    previewEnabled = state.networkConnected && state.authoritative,
                                    canResolve = state.canMutate, onResolveConflict = model::resolveMediaConflict,
                                    onRetryPersistence = model::retryEditorPersistence, onPhotoDuration = model::editPhotoDuration)
                                if (uploads != null) {
                                    val rows by uploads.rows.collectAsStateWithLifecycle()
                                    val runningSinceMillis by uploads.runningSinceMillis.collectAsStateWithLifecycle()
                                    val issue by uploads.issue.collectAsStateWithLifecycle()
                                    val resolving by uploads.resolvingId.collectAsStateWithLifecycle()
                                    val writeAccess by uploads.writeAccess.collectAsStateWithLifecycle()
                                    val network by uploads.network.state.collectAsStateWithLifecycle()
                                     UploadPanel(rows, issue, uploads::enqueue, uploads::pause, uploads::resume, uploads::retry, uploads::dismiss,
                                        resolving, uploads::resolve, uploads::refresh, uploads::preview,
                                        selectionEnabled = state.review.target?.action != ReviewAction.UPLOAD || model.reviewUploadPackageId != null,
                                        selectionPackageId = model.reviewUploadPackageId,
                                        onSelectPackage = { uris, expected ->
                                            if (expected != null) model.enqueueReviewUploads(expected) { uploads.enqueue(uris, it) }
                                            else if (state.review.target?.action != ReviewAction.UPLOAD) uploads.enqueue(uris)
                                        }, canMutate = state.canMutate && writeAccess != null && writeAccess == model.currentBinding,
                                        runningSinceMillis = runningSinceMillis,
                                        selectionContext = model.currentBinding?.takeIf { state.networkConnected && network.connected }?.let {
                                            "${state.origin}:$it:${network.epoch}:${state.review.target?.occurrenceId}:${state.review.target?.reviewId}:${state.review.target?.action}"
                                        })
                                    OutlinedButton(onClick = model::refresh, enabled = !state.busy) { Text(stringResource(R.string.refresh)) }
                                }
                                PendingPanel(state.dashboard, state.canMutate && !state.stale, onPending)
                            }
                            Destination.COMPLETED -> CompletedPackagesScreen(state, model::selectCompleted, model::refreshCompleted, model::downloadMediaPreview)
                            Destination.ACTIVITY -> {
                                state.outcomePackage?.let { Text(stringResource(R.string.publication_context, it)) }
                                ApprovalInbox(state.dashboard, state.stale, model::refresh, onPending, canMutate = state.canMutate)
                                HorizontalDivider()
                                ActivityScreen(state.activity, state.activityFetchedAt, state.busy || !state.networkConnected, model::refresh)
                            }
                            Destination.SETTINGS -> {
                                SettingsScreen(state, model, openUrl)
                                if (push != null) {
                                    val availability by push.availability.collectAsStateWithLifecycle()
                                    Text(stringResource(when (availability) {
                                        PushAvailability.UNCONFIGURED -> R.string.push_unconfigured
                                        PushAvailability.SERVICES_UNAVAILABLE -> R.string.push_services_unavailable
                                        PushAvailability.PERMISSION_DENIED -> R.string.push_denied
                                        PushAvailability.REGISTRATION_FAILED -> R.string.push_registration_failed
                                        PushAvailability.REGISTERING -> R.string.push_registering
                                        PushAvailability.AVAILABLE -> R.string.push_available
                                    }))
                                    OutlinedButton(onClick = onNotificationPermission) { Text(stringResource(R.string.push_enable)) }
                                    TextButton(onClick = onNotificationSettings) { Text(stringResource(R.string.push_settings)) }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
@Composable private fun NavigationIcon(item: Destination) {
    Icon(when (item) { Destination.DASHBOARD -> Icons.Default.Home; Destination.PACKAGE -> Icons.Default.Star;
        Destination.COMPLETED -> Icons.Default.CheckCircle; Destination.ACTIVITY -> Icons.Default.List; Destination.SETTINGS -> Icons.Default.Settings }, contentDescription = null)
}
fun destinationLabel(item: Destination) = when (item) {
    Destination.DASHBOARD -> R.string.dashboard; Destination.PACKAGE -> R.string.package_nav
    Destination.COMPLETED -> R.string.completed_nav; Destination.ACTIVITY -> R.string.activity; Destination.SETTINGS -> R.string.settings
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
                    ?: Text(stringResource(R.string.update_download_unavailable))
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
fun issueLabel(issue: UiIssue) = when (issue) {
    UiIssue.INVALID_SERVER -> R.string.invalid_server; UiIssue.NETWORK -> R.string.network_error
    UiIssue.INVALID_CODE -> R.string.invalid_code; UiIssue.RATE_LIMIT -> R.string.rate_limit
    UiIssue.INVALID_INPUT -> R.string.invalid_input; UiIssue.PROVIDER_UNAVAILABLE -> R.string.provider_unavailable
    UiIssue.POLICY_MISSING -> R.string.policy_missing; UiIssue.POLICY_CHANGED -> R.string.policy_changed
    UiIssue.STORAGE -> R.string.storage_error; UiIssue.UNKNOWN -> R.string.unknown_error
}
