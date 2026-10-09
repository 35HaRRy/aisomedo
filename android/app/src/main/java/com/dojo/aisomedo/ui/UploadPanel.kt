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

fun uploadIssueLabel(issue: UploadIssue): Int = when (issue) {
    UploadIssue.NETWORK -> R.string.network_error; UploadIssue.OVERSIZE -> R.string.upload_oversize
    UploadIssue.CAPACITY -> R.string.upload_capacity; UploadIssue.PACKAGE_CHANGED -> R.string.upload_package_changed
    UploadIssue.CHECKSUM -> R.string.upload_checksum; UploadIssue.WRONG_FILE -> R.string.upload_wrong_file
    UploadIssue.FILE_ACCESS -> R.string.upload_file_access; UploadIssue.STORAGE -> R.string.upload_storage
    UploadIssue.SCHEDULING -> R.string.upload_scheduling; UploadIssue.NOTIFICATIONS -> R.string.upload_notifications
    UploadIssue.EXPIRED -> R.string.upload_expired; UploadIssue.CONFLICT -> R.string.upload_conflict
    UploadIssue.AUTH -> R.string.pair_help; UploadIssue.UPDATE_REQUIRED -> R.string.update_help
    UploadIssue.SERVER -> R.string.upload_server_error; UploadIssue.INVALID_RESPONSE -> R.string.unknown_error
}

@OptIn(ExperimentalLayoutApi::class)
@Composable fun UploadPanel(
    rows: List<UploadRecord>, issue: UploadIssue?, onSelect: (List<Uri>) -> Unit,
    onPause: (String) -> Unit, onResume: (String, Uri?) -> Unit, onRetry: (String, Uri?) -> Unit, onDismiss: (String) -> Unit,
) {
    val context = LocalContext.current
    var pendingUris by rememberSaveable { mutableStateOf(arrayListOf<String>()) }
    var replacementId by rememberSaveable { mutableStateOf<String?>(null) }
    var pickerIssue by remember { mutableStateOf<UploadIssue?>(null) }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        onSelect(pendingUris.map(Uri::parse)); pendingUris = arrayListOf()
    }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (uris.isNotEmpty()) {
            if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                pendingUris = ArrayList(uris.map(Uri::toString)); permission.launch(Manifest.permission.POST_NOTIFICATIONS)
            } else onSelect(uris)
        }
    }
    val original = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        val id = replacementId
        replacementId = null
        if (id != null && uri != null) onResume(id, uri)
    }
    Column(Modifier.widthIn(max = 640.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Button(onClick = {
            try { picker.launch(arrayOf("image/*", "video/*")); pickerIssue = null }
            catch (_: Exception) { pickerIssue = UploadIssue.FILE_ACCESS }
        }) { Text(stringResource(R.string.upload_select)) }
        Text(stringResource(R.string.upload_help), style = MaterialTheme.typography.bodyMedium)
        (pickerIssue ?: issue)?.let { error ->
            Text(stringResource(uploadIssueLabel(error)), color = MaterialTheme.colorScheme.error, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
            if (error == UploadIssue.NOTIFICATIONS) TextButton(onClick = {
                try { context.startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)) }
                catch (_: Exception) { pickerIssue = UploadIssue.NOTIFICATIONS }
            }) { Text(stringResource(R.string.upload_notification_settings)) }
        }
        rows.forEach { row -> key(row.id) {
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
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    when (row.phase) {
                        UploadPhase.PREPARING, UploadPhase.WAITING, UploadPhase.UPLOADING -> OutlinedButton(onClick = { onPause(row.id) }) { Text(stringResource(R.string.upload_pause)) }
                        UploadPhase.PAUSED -> OutlinedButton(onClick = { onResume(row.id, null) }) { Text(stringResource(R.string.upload_resume)) }
                        UploadPhase.RETRYABLE, UploadPhase.FAILED, UploadPhase.EXPIRED -> OutlinedButton(onClick = { onRetry(row.id, null) }) { Text(stringResource(R.string.retry)) }
                        UploadPhase.NEEDS_FILE -> OutlinedButton(onClick = {
                            replacementId = row.id
                            try { original.launch(arrayOf("image/*", "video/*")); pickerIssue = null }
                            catch (_: Exception) { pickerIssue = UploadIssue.FILE_ACCESS }
                        }) { Text(stringResource(R.string.upload_original)) }
                        else -> Unit
                    }
                    if (row.phase !in setOf(UploadPhase.PREPARING, UploadPhase.WAITING, UploadPhase.UPLOADING, UploadPhase.QUEUED, UploadPhase.PROCESSING)) TextButton(onClick = { onDismiss(row.id) }) { Text(stringResource(R.string.upload_dismiss)) }
                }
            }
        } }
    }
}
