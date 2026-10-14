package com.dojo.aisomedo.ui

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.*
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.dojo.aisomedo.R
import com.dojo.aisomedo.uploads.*
import com.dojo.aisomedo.api.ResolveConflictIn
import kotlinx.coroutines.delay
import java.io.File

fun uploadIssueLabel(issue: UploadIssue): Int = when (issue) {
    UploadIssue.NETWORK -> R.string.upload_network_error; UploadIssue.OVERSIZE -> R.string.upload_oversize
    UploadIssue.TIMEOUT -> R.string.upload_timeout; UploadIssue.DNS -> R.string.upload_dns
    UploadIssue.TLS -> R.string.upload_tls; UploadIssue.RATE_LIMIT -> R.string.upload_rate_limit
    UploadIssue.FORBIDDEN -> R.string.upload_forbidden; UploadIssue.INVALID_INPUT -> R.string.upload_invalid_input
    UploadIssue.CAPACITY -> R.string.upload_capacity; UploadIssue.PACKAGE_CHANGED -> R.string.upload_package_changed
    UploadIssue.CHECKSUM -> R.string.upload_checksum; UploadIssue.WRONG_FILE -> R.string.upload_wrong_file
    UploadIssue.FILE_ACCESS -> R.string.upload_file_access; UploadIssue.STORAGE -> R.string.upload_storage
    UploadIssue.SCHEDULING -> R.string.upload_scheduling; UploadIssue.NOTIFICATIONS -> R.string.upload_notifications
    UploadIssue.EXPIRED -> R.string.upload_expired; UploadIssue.CONFLICT -> R.string.upload_conflict
    UploadIssue.AUTH -> R.string.pair_help; UploadIssue.UPDATE_REQUIRED -> R.string.update_help
    UploadIssue.SERVER -> R.string.upload_server_error; UploadIssue.INVALID_RESPONSE -> R.string.upload_invalid_response
}

@OptIn(ExperimentalLayoutApi::class)
@Composable fun UploadPanel(
    rows: List<UploadRecord>, issue: UploadIssue?, onSelect: (List<Uri>) -> Unit,
    onPause: (String) -> Unit, onResume: (String, Uri?) -> Unit, onRetry: (String, Uri?) -> Unit, onDismiss: (String) -> Unit,
    resolvingId: String? = null, onResolve: (String, ResolveConflictIn) -> Unit = { _, _ -> }, onRefresh: suspend () -> Unit = {},
    onPreview: suspend (String, ConflictTarget, File) -> Unit = { _, _, _ -> throw UploadFailure(UploadIssue.FILE_ACCESS) },
    selectionEnabled: Boolean = true, selectionPackageId: Int? = null,
    onSelectPackage: (List<Uri>, Int?) -> Unit = { uris, _ -> onSelect(uris) },
    canMutate: Boolean = true,
    selectionContext: String? = "local",
    runningSinceMillis: Map<String, Long> = emptyMap(),
) {
    val currentSelectionContext by rememberUpdatedState(selectionContext)
    val context = LocalContext.current
    var pendingUris by rememberSaveable { mutableStateOf(arrayListOf<String>()) }
    var replacementId by rememberSaveable { mutableStateOf<String?>(null) }
    var pickerIssue by remember { mutableStateOf<UploadIssue?>(null) }
    var pickerPackageId by rememberSaveable { mutableStateOf<Int?>(null) }
    var pickerContext by rememberSaveable { mutableStateOf<String?>(null) }
    var permissionPending by rememberSaveable { mutableStateOf(false) }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        permissionPending = false
    }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (pickerContext != null && pickerContext == currentSelectionContext && uris.isNotEmpty()) {
            pendingUris = ArrayList(uris.map(Uri::toString))
            if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                permissionPending = true
                permission.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }
    }
    val original = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (pickerContext != null && pickerContext == currentSelectionContext && replacementId != null && uri != null) {
            pendingUris = arrayListOf(uri.toString())
        } else replacementId = null
    }
    LaunchedEffect(selectionContext, canMutate, selectionEnabled, selectionPackageId, pendingUris, permissionPending) {
        if (pickerContext != selectionContext) {
            pendingUris = arrayListOf(); replacementId = null; pickerContext = null
        } else if (pickerContext != null && canMutate && !permissionPending && pendingUris.isNotEmpty()) {
            val uris = pendingUris.map(Uri::parse)
            val id = replacementId
            if (id == null && !selectionEnabled) return@LaunchedEffect
            pendingUris = arrayListOf(); replacementId = null
            if (id != null) onResume(id, uris.single())
            else if (pickerPackageId == selectionPackageId) onSelectPackage(uris, pickerPackageId)
            else pickerIssue = UploadIssue.PACKAGE_CHANGED
        }
    }
    Column(Modifier.widthIn(max = 640.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Button(enabled = canMutate && resolvingId == null && selectionEnabled && pendingUris.isEmpty() && !permissionPending, onClick = {
            pickerPackageId = selectionPackageId
            pickerContext = selectionContext
            try { picker.launch(arrayOf("image/*", "video/*")); pickerIssue = null }
            catch (_: Exception) { pickerIssue = UploadIssue.FILE_ACCESS }
        }) { Text(stringResource(R.string.upload_select)) }
        Text(stringResource(R.string.upload_help), style = MaterialTheme.typography.bodyMedium)
        if (pendingUris.isNotEmpty()) Text(stringResource(R.string.upload_selection_waiting),
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
        (pickerIssue ?: issue)?.let { error ->
            Text(stringResource(uploadIssueLabel(error)), color = MaterialTheme.colorScheme.error, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
            if (error == UploadIssue.NOTIFICATIONS) TextButton(onClick = {
                try { context.startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)) }
                catch (_: Exception) { pickerIssue = UploadIssue.NOTIFICATIONS }
            }) { Text(stringResource(R.string.upload_notification_settings)) }
        }
        rows.forEach { row -> key(row.id, row.bindingId) {
            val runningSince = runningSinceMillis[row.id]?.takeIf { row.intent == UploadIntent.ACTIVE &&
                row.phase in setOf(UploadPhase.WAITING, UploadPhase.PREPARING, UploadPhase.UPLOADING, UploadPhase.RETRYABLE) }
            UploadDelayWarning(row.filename, runningSince) { onPause(row.id) }
            Column(Modifier.fillMaxWidth().testTag("upload-row-${row.id}"), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                HorizontalDivider()
                Text(row.filename, style = MaterialTheme.typography.titleMedium)
                Text(stringResource(phaseLabel(row.phase)), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
                val size = row.size ?: 0
                val received = row.status?.receivedBytes ?: 0
                val ratio = if (size > 0) (received.toDouble() / size).toFloat().coerceIn(0f, 1f) else 0f
                val progress = Modifier.fillMaxWidth().testTag("upload-progress-${row.id}")
                if (row.phase == UploadPhase.PREPARING || size == 0L) LinearProgressIndicator(modifier = progress)
                else {
                    LinearProgressIndicator(progress = { ratio }, modifier = progress)
                    Text(stringResource(R.string.upload_bytes, received, size, (ratio * 100).toInt()), style = MaterialTheme.typography.bodySmall)
                }
                row.issue?.let { Text(stringResource(uploadIssueLabel(it)), color = MaterialTheme.colorScheme.error) }
                row.diagnostic?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                if (row.phase == UploadPhase.CONFLICT) key(row.bindingId, row.status?.conflicts) {
                    ConflictControls(row, resolvingId != null, onResolve, onRefresh, onPreview, canMutate = canMutate)
                }
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    when (row.phase) {
                        UploadPhase.PREPARING, UploadPhase.WAITING, UploadPhase.UPLOADING -> OutlinedButton(onClick = { onPause(row.id) }) { Text(stringResource(R.string.upload_pause)) }
                        UploadPhase.PAUSED -> OutlinedButton(onClick = { onResume(row.id, null) }) { Text(stringResource(R.string.upload_resume)) }
                        UploadPhase.RETRYABLE, UploadPhase.FAILED, UploadPhase.EXPIRED -> {
                            if (eligible(row) || runningSince != null) OutlinedButton(onClick = { onPause(row.id) }) { Text(stringResource(R.string.upload_pause)) }
                            OutlinedButton(onClick = { onRetry(row.id, null) }, enabled = canMutate && runningSince == null) { Text(stringResource(R.string.retry)) }
                        }
                        UploadPhase.NEEDS_FILE -> OutlinedButton(enabled = canMutate, onClick = {
                            replacementId = row.id
                            pickerContext = selectionContext
                            try { original.launch(arrayOf("image/*", "video/*")); pickerIssue = null }
                            catch (_: Exception) { pickerIssue = UploadIssue.FILE_ACCESS }
                        }) { Text(stringResource(R.string.upload_original)) }
                        else -> Unit
                    }
                    if (row.phase !in setOf(UploadPhase.PREPARING, UploadPhase.WAITING, UploadPhase.UPLOADING, UploadPhase.QUEUED, UploadPhase.PROCESSING)) TextButton(enabled = canMutate && resolvingId == null, onClick = { onDismiss(row.id) }) { Text(stringResource(R.string.upload_dismiss)) }
                }
            }
        } }
    }
}

@Composable private fun UploadDelayWarning(filename: String, startedAtMillis: Long?, onStop: () -> Unit) {
    var acknowledged by rememberSaveable(startedAtMillis) { mutableStateOf(false) }
    var show by remember(startedAtMillis) { mutableStateOf(false) }
    LaunchedEffect(startedAtMillis, acknowledged) {
        if (startedAtMillis != null && !acknowledged) {
            delay((60_000L - (System.currentTimeMillis() - startedAtMillis)).coerceIn(0L, 60_000L))
            show = true
        }
    }
    fun continueUpload() { acknowledged = true; show = false }
    if (show && startedAtMillis != null) AlertDialog(
        onDismissRequest = ::continueUpload,
        title = { Text(stringResource(R.string.upload_slow_title)) },
        text = { Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(filename, maxLines = 3, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis)
            Text(stringResource(R.string.upload_slow_help))
        } },
        confirmButton = { TextButton(onClick = { continueUpload(); onStop() }) { Text(stringResource(R.string.upload_stop)) } },
        dismissButton = { TextButton(onClick = ::continueUpload) { Text(stringResource(R.string.upload_resume)) } },
    )
}
