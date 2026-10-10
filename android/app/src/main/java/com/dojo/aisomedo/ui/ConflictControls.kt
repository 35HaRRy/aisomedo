package com.dojo.aisomedo.ui

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.widget.MediaController
import android.widget.VideoView
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.*
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.dojo.aisomedo.R
import com.dojo.aisomedo.api.ResolveConflictIn
import com.dojo.aisomedo.uploads.*
import kotlinx.coroutines.*
import java.io.File

data class ConflictSelection(
    val decision: String = "keep_both", val targetId: String? = null, val applyAll: Boolean = false,
    val previewReady: Boolean = false, val confirmed: Boolean = false,
) {
    fun choose(value: String) = copy(decision = value, confirmed = false)
    fun target(value: String) = copy(targetId = value, previewReady = false, confirmed = false)
    fun bulk(value: Boolean) = copy(applyAll = value, confirmed = false)
    fun preview(ready: Boolean) = copy(previewReady = ready, confirmed = false)
    fun canApply(busy: Boolean) = !busy && decision in conflictDecisions &&
        (decision != "keep_selected" || (!targetId.isNullOrBlank() && previewReady && confirmed))
    fun body(): ResolveConflictIn {
        check(canApply(false))
        return ResolveConflictIn(decision = decision, applyToAll = applyAll,
            targetMediaId = targetId.takeIf { decision == "keep_selected" }, confirmedOverwrite = decision == "keep_selected")
    }
}

@Composable fun ConflictControls(
    row: UploadRecord, busy: Boolean, onResolve: (String, ResolveConflictIn) -> Unit, onRefresh: suspend () -> Unit,
    onPreview: suspend (String, ConflictTarget, File) -> Unit,
) {
    val targets = remember(row.status?.conflicts) { conflictTargets(row.status) }
    var choice by remember { mutableStateOf(ConflictSelection(targetId = targets.firstOrNull()?.mediaId)) }
    var refreshAttempt by remember { mutableIntStateOf(0) }
    var refreshing by remember { mutableStateOf(false) }
    var refreshFailed by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val blocked = busy || refreshing || row.pendingDecision != null
    val target = targets.find { it.mediaId == choice.targetId }
    val overwrite = choice.decision == "keep_selected"
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(stringResource(R.string.conflict_title), style = MaterialTheme.typography.titleMedium, modifier = Modifier.semantics { heading() })
        if (targets.size > 1) Column(Modifier.selectableGroup()) {
            Text(stringResource(R.string.conflict_target), style = MaterialTheme.typography.labelLarge)
            targets.forEach { value ->
                Row(Modifier.fillMaxWidth().heightIn(min = 48.dp).selectable(value == target, enabled = !blocked, role = Role.RadioButton,
                    onClick = { choice = choice.target(value.mediaId) }), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    RadioButton(value == target, onClick = null, enabled = !blocked)
                    Text("${value.filename} · ${value.mediaId}", Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
                }
            }
        }
        if (target != null) {
            Text(target.filename, style = MaterialTheme.typography.titleSmall)
            Text(stringResource(R.string.conflict_metadata, target.sizeBytes, target.uploadedAt, target.mediaId), style = MaterialTheme.typography.bodySmall)
            if (!refreshing) key(target, refreshAttempt) { ConflictPreview(row.id, target, onPreview, { choice = choice.preview(it) }) }
        } else Text(stringResource(R.string.conflict_no_target), style = MaterialTheme.typography.bodyMedium)
        Column(Modifier.selectableGroup()) {
            for ((decision, label) in listOf("keep_both" to R.string.conflict_keep_both, "keep_selected" to R.string.conflict_keep_selected,
                "keep_target" to R.string.conflict_keep_target)) {
                val enabled = !blocked && (decision != "keep_selected" || target != null)
                Row(Modifier.fillMaxWidth().heightIn(min = 48.dp).selectable(choice.decision == decision, enabled = enabled, role = Role.RadioButton,
                    onClick = { choice = choice.choose(decision) }), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    RadioButton(choice.decision == decision, onClick = null, enabled = enabled)
                    Text(stringResource(label), Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
                }
            }
        }
        ConflictCheckbox(choice.applyAll, !blocked, R.string.conflict_apply_all) { choice = choice.bulk(it) }
        Text(stringResource(R.string.conflict_bulk_help), style = MaterialTheme.typography.bodySmall)
        if (overwrite) {
            Text(stringResource(R.string.conflict_warning), color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodyLarge, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Assertive })
            if (choice.applyAll) Text(stringResource(R.string.conflict_bulk_warning), color = MaterialTheme.colorScheme.error)
            ConflictCheckbox(choice.confirmed, !blocked && choice.previewReady, R.string.conflict_confirm) { choice = choice.copy(confirmed = it) }
        }
        Button(onClick = {
            val body = choice.body()
            choice = choice.copy(confirmed = false)
            onResolve(row.id, body)
        }, enabled = choice.canApply(blocked), colors = if (overwrite) ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error,
            contentColor = MaterialTheme.colorScheme.onError) else ButtonDefaults.buttonColors()) {
            Text(stringResource(if (overwrite) R.string.conflict_overwrite else R.string.conflict_apply))
        }
        TextButton(onClick = { scope.launch {
            choice = choice.preview(false); refreshing = true; refreshFailed = false
            try { onRefresh() }
            catch (e: CancellationException) { throw e }
            catch (_: Exception) { refreshFailed = true }
            finally { refreshAttempt++; refreshing = false }
        } }, enabled = !busy && !refreshing) { Text(stringResource(R.string.refresh)) }
        if (refreshing) Text(stringResource(R.string.loading), modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
        if (refreshFailed) Text(stringResource(R.string.unknown_error), color = MaterialTheme.colorScheme.error)
        if (row.pendingDecision != null && !busy) Text(stringResource(R.string.conflict_uncertain), modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
        if (busy) Text(stringResource(R.string.conflict_resolving), modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
    }
}

@Composable private fun ConflictCheckbox(checked: Boolean, enabled: Boolean, label: Int, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().heightIn(min = 48.dp).toggleable(checked, enabled = enabled, role = Role.Checkbox, onValueChange = onChange),
        horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Checkbox(checked, onCheckedChange = null, enabled = enabled)
        Text(stringResource(label), Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
    }
}

@Composable private fun ConflictPreview(id: String, target: ConflictTarget, load: suspend (String, ConflictTarget, File) -> Unit, onReady: (Boolean) -> Unit) {
    val context = LocalContext.current
    val loader by rememberUpdatedState(load)
    val ready by rememberUpdatedState(onReady)
    var attempt by remember { mutableIntStateOf(0) }
    var image by remember(attempt) { mutableStateOf<Bitmap?>(null) }
    var video by remember(attempt) { mutableStateOf<File?>(null) }
    var loading by remember(attempt) { mutableStateOf(true) }
    var failed by remember(attempt) { mutableStateOf(false) }
    val label = stringResource(R.string.conflict_preview, target.filename)
    DisposableEffect(image) {
        val bitmap = image
        onDispose { bitmap?.recycle() }
    }
    LaunchedEffect(target, attempt) {
        var file: File? = null
        try {
            ready(false)
            val temporary = withContext(Dispatchers.IO) {
                val directory = context.cacheDir.resolve("conflict-previews")
                check(directory.isDirectory || directory.mkdirs())
                File.createTempFile("target-", if (target.contentType == "video/mp4") ".mp4" else ".jpg", directory).also { file = it }
            }
            loader(id, target, temporary)
            if (target.contentType == "video/mp4") video = temporary
            else {
                image = withContext(Dispatchers.Default) {
                    val options = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                    BitmapFactory.decodeFile(temporary.absolutePath, options)
                    require(options.outWidth in 1..16384 && options.outHeight in 1..16384)
                    options.inJustDecodeBounds = false
                    options.inSampleSize = 1
                    while (maxOf(options.outWidth, options.outHeight) / options.inSampleSize > 1024) options.inSampleSize *= 2
                    BitmapFactory.decodeFile(temporary.absolutePath, options) ?: error("Invalid preview")
                }
                loading = false
                ready(true)
            }
            awaitCancellation()
        } catch (e: CancellationException) {
            currentCoroutineContext().ensureActive()
            failed = true; loading = false; ready(false)
        }
        catch (_: Exception) { failed = true; loading = false; ready(false) }
        finally { file?.delete() }
    }
    image?.let { Image(it.asImageBitmap(), contentDescription = label, modifier = Modifier.fillMaxWidth().heightIn(max = 240.dp)) }
    video?.let { file -> key(file) {
        ConflictVideo(file, label, { loading = false; ready(true) }, { file.delete(); failed = true; loading = false; video = null; ready(false) })
    } }
    if (loading) Text(stringResource(R.string.conflict_preview_loading), modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
    if (failed) {
        Text(stringResource(R.string.conflict_preview_failed), color = MaterialTheme.colorScheme.error, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
        TextButton(onClick = { ready(false); attempt++ }) { Text(stringResource(R.string.retry)) }
    }
}

@Composable private fun ConflictVideo(file: File, label: String, onReady: () -> Unit, onError: () -> Unit) {
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    var player: VideoView? by remember { mutableStateOf(null) }
    val ready by rememberUpdatedState(onReady)
    val error by rememberUpdatedState(onError)
    DisposableEffect(lifecycle) {
        val observer = LifecycleEventObserver { _, event -> if (event == Lifecycle.Event.ON_STOP) player?.pause() }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer) }
    }
    AndroidView(factory = { context -> VideoView(context).apply {
        player = this
        contentDescription = label
        val view = this
        setMediaController(MediaController(context).apply { setAnchorView(view) })
        setOnPreparedListener { seekTo(1); ready() }
        setOnErrorListener { _, _, _ -> stopPlayback(); error(); true }
        setVideoPath(file.absolutePath)
    } }, modifier = Modifier.fillMaxWidth().height(240.dp), onRelease = {
        it.setOnPreparedListener(null); it.setOnErrorListener(null); it.stopPlayback(); player = null
    })
}
