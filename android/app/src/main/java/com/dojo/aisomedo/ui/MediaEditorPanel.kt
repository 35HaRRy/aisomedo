package com.dojo.aisomedo.ui

import androidx.activity.compose.BackHandler
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.scrollBy
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Check
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.LayoutCoordinates
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.*
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.dojo.aisomedo.R
import com.dojo.aisomedo.api.EditorMediaOut
import com.dojo.aisomedo.editor.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import java.io.File
import java.util.Locale

private data class DropTarget(val id: String, val after: Boolean)
private fun seconds(value: Double) = String.format(Locale.ROOT, "%.2f", value)

@OptIn(ExperimentalLayoutApi::class, ExperimentalMaterial3Api::class)
@Composable fun MediaEditorPanel(
    editor: MediaEditorState, busy: Boolean, scroll: ScrollState, viewport: Rect,
    onRefresh: () -> Unit, onReorder: (List<String>) -> Unit, onRemove: (String, Boolean) -> Unit, onRestore: (String) -> Unit,
    onEditRanges: (String, List<RangeInput>) -> Unit, onSave: (String) -> Unit, onDiscard: (String) -> Unit,
    canMutate: Boolean = true,
    onPreview: suspend (String, File) -> Unit = { _, _ -> },
    previewEnabled: Boolean = true,
    canResolve: Boolean = canMutate,
    onResolveConflict: (String, Boolean) -> Unit = { _, _ -> },
    onRetryPersistence: () -> Unit = {},
    onPhotoDuration: (String, String) -> Unit = { _, _ -> },
    onRetryPreview: (String) -> Unit = {},
    onClear: (Boolean) -> Unit = {},
    onDiscardReplaced: () -> Unit = {},
    canClear: Boolean = canMutate,
    pendingClearFolder: String? = null,
) {
    val snapshot = editor.snapshot
    val blocked = !canMutate || busy || editor.readRequired || editor.persistenceIssue != null || snapshot?.`package`?.status == "completed"
    val order = snapshot?.montage?.order.orEmpty()
    val byId = snapshot?.media.orEmpty().associateBy { it.mediaId }
    val ordered = order.mapNotNull(byId::get).filter { it.status == "finalized" }
    val bounds = remember { mutableMapOf<String, Rect>() }
    var dragged by remember { mutableStateOf<String?>(null) }
    var pointer by remember { mutableStateOf(Offset.Zero) }
    var target by remember { mutableStateOf<DropTarget?>(null) }
    var opened by rememberSaveable(snapshot?.`package`?.folderName) { mutableStateOf<String?>(null) }
    var previewed by rememberSaveable(snapshot?.`package`?.folderName) { mutableStateOf<String?>(null) }
    var removing by remember { mutableStateOf<String?>(null) }
    var clearing by remember { mutableStateOf(false) }
    val currentViewport by rememberUpdatedState(viewport)
    val currentOrder by rememberUpdatedState(order)
    val currentReorder by rememberUpdatedState(onReorder)
    val edge = with(LocalDensity.current) { 56.dp.toPx() }
    val speed = with(LocalDensity.current) { 12.dp.toPx() }
    fun clearDrag() { dragged = null; target = null }
    fun findTarget(): DropTarget? {
        if (!currentViewport.contains(pointer)) return null
        val row = currentOrder.mapNotNull { id -> bounds[id]?.let { id to it } }
            .filter { (_, rect) -> pointer.x in rect.left..rect.right }
            .minByOrNull { (_, rect) -> when { pointer.y < rect.top -> rect.top - pointer.y; pointer.y > rect.bottom -> pointer.y - rect.bottom; else -> 0f } }
            ?: return null
        return DropTarget(row.first, pointer.y > row.second.center.y).takeIf { it.id != dragged }
    }
    BackHandler(dragged != null) { clearDrag() }
    LaunchedEffect(snapshot?.`package`?.id, snapshot?.contentRevision, previewEnabled) { previewed = null }
    LaunchedEffect(blocked, snapshot?.`package`?.folderName, order) { clearDrag() }
    LaunchedEffect(dragged) {
        while (dragged != null) {
            val view = currentViewport
            if (pointer.x in view.left..view.right && pointer.y in view.top..view.bottom) {
                val amount = when {
                    pointer.y < view.top + edge -> -speed * ((view.top + edge - pointer.y) / edge).coerceIn(0f, 1f)
                    pointer.y > view.bottom - edge -> speed * ((pointer.y - view.bottom + edge) / edge).coerceIn(0f, 1f)
                    else -> 0f
                }
                if (amount != 0f) scroll.scrollBy(amount)
            }
            target = findTarget()
            delay(16)
        }
    }
    CollapsiblePanel(stringResource(R.string.media_management), actions = {
        MediaIconAction(stringResource(R.string.refresh), Icons.Default.Refresh, !busy, onClick = onRefresh)
        MediaIconAction(stringResource(if (pendingClearFolder == null) R.string.media_clear else R.string.media_retry_clear), Icons.Default.Delete, !busy && canClear, onClick = { clearing = true })
    }) {
        editor.persistenceIssue?.let { issue ->
            Text(stringResource(if (issue == DraftIssue.STORAGE) R.string.draft_storage_failed else R.string.draft_corrupt),
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.testTag("draft-storage-warning").semantics { liveRegion = LiveRegionMode.Assertive })
            if (issue == DraftIssue.STORAGE) OutlinedButton(onClick = onRetryPersistence, enabled = !busy && canResolve,
                modifier = Modifier.testTag("draft-storage-retry")) { Text(stringResource(R.string.draft_storage_retry)) }
        }
        if (editor.storedDraft != null && (snapshot == null || editor.storedDraft.folderName != snapshot.`package`.folderName || snapshot.`package`.status != "active")) {
            Text(stringResource(R.string.draft_inapplicable, editor.storedDraft.folderName), modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
            TextButton(onClick = onDiscardReplaced, enabled = canResolve && !busy) { Text(stringResource(R.string.media_discard)) }
        }
        for ((key, server) in editor.conflicts) {
            val id = key.substringAfter(':')
            Text(stringResource(R.string.draft_conflict, byId[id]?.filename ?: id), style = MaterialTheme.typography.titleSmall,
                modifier = Modifier.testTag("draft-conflict-$key").semantics { liveRegion = LiveRegionMode.Polite })
            Text(stringResource(R.string.draft_local_values, editor.inputs[id].orEmpty().joinToString("; ") { "${it.start}–${it.end} s" }))
            val ranges = (server["ranges"] as? kotlinx.serialization.json.JsonArray)?.joinToString("; ") { row ->
                val range = row as? kotlinx.serialization.json.JsonObject
                "${range?.get("start")}–${range?.get("end")} s"
            }
            Text(stringResource(R.string.draft_server_values, ranges?.ifEmpty { stringResource(R.string.range_whole) } ?: stringResource(R.string.media_no_active)))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { onResolveConflict(key, true) }, enabled = canResolve && !busy && "status" !in server && editor.persistenceIssue == null) { Text(stringResource(R.string.draft_use_local)) }
                OutlinedButton(onClick = { onResolveConflict(key, false) }, enabled = canResolve && !busy && editor.persistenceIssue == null) { Text(stringResource(R.string.draft_use_server)) }
            }
        }
        editor.issue?.let { issue -> Text(stringResource(when (issue) {
            EditorIssue.READ -> R.string.media_read_failed; EditorIssue.CONFLICT -> R.string.media_changed
            EditorIssue.INVALID -> R.string.media_invalid; EditorIssue.LIMIT -> R.string.media_limit_failed
            EditorIssue.UNCERTAIN -> R.string.media_uncertain
        }), color = MaterialTheme.colorScheme.error, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Assertive }) }
        if (snapshot == null) Text(stringResource(if (busy) R.string.loading else R.string.media_no_active))
        else {
            val total = editor.proposedTotal
            Text(stringResource(R.string.media_drag_help), style = MaterialTheme.typography.bodySmall)
            ordered.forEachIndexed { index, media -> key(media.mediaId) {
                val id = media.mediaId
                var handle by remember { mutableStateOf<LayoutCoordinates?>(null) }
                val before = target == DropTarget(id, false)
                val after = target == DropTarget(id, true)
                Column(Modifier.fillMaxWidth().then(if (opened == id) Modifier else Modifier.height(480.dp)).testTag("media-row-$id")
                    .onGloballyPositioned { coordinates ->
                        bounds[id] = Rect(coordinates.localToRoot(Offset.Zero), coordinates.localToRoot(Offset(coordinates.size.width.toFloat(), coordinates.size.height.toFloat())))
                    }.background(if (dragged == id) MaterialTheme.colorScheme.secondaryContainer else MaterialTheme.colorScheme.surface),
                    verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    HorizontalDivider(thickness = if (before) 3.dp else 1.dp, color = if (before) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outlineVariant,
                        modifier = if (before) Modifier.testTag("media-insertion-$id-before") else Modifier)
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.size(48.dp).testTag("media-drag-$id").onGloballyPositioned { handle = it }
                            .semantics { if (blocked) disabled() }
                            .pointerInput(blocked, id, order) {
                                if (!blocked) detectDragGestures(
                                    onDragStart = { position -> handle?.let { dragged = id; pointer = it.localToRoot(position); target = findTarget() } },
                                    onDragCancel = { clearDrag() },
                                    onDragEnd = {
                                        val from = dragged
                                        val drop = findTarget()
                                        clearDrag()
                                        if (from != null && drop != null) {
                                            val next = moveMedia(currentOrder, from, drop.id, drop.after)
                                            if (next != currentOrder) currentReorder(next)
                                        }
                                    },
                                    onDrag = { change, _ -> change.consume(); handle?.let { pointer = it.localToRoot(change.position); target = findTarget() } },
                                )
                            }, contentAlignment = Alignment.Center) {
                            Icon(Icons.Default.Menu, contentDescription = stringResource(R.string.media_drag_label, media.filename), tint = if (blocked) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.primary)
                        }
                        TooltipBox(positionProvider = TooltipDefaults.rememberPlainTooltipPositionProvider(), tooltip = { PlainTooltip { Text(media.filename) } },
                            state = rememberTooltipState(), modifier = Modifier.weight(1f)) {
                            Text(stringResource(R.string.media_position, index + 1, media.filename), maxLines = 1, overflow = TextOverflow.Ellipsis,
                                style = MaterialTheme.typography.titleMedium, modifier = Modifier.semantics { contentDescription = media.filename })
                        }
                        IconButton(onClick = { onReorder(moveMedia(order, id, order[index - 1], false)) }, enabled = !blocked && index > 0, modifier = Modifier.testTag("media-up-$id")) {
                            Icon(Icons.Default.KeyboardArrowUp, contentDescription = stringResource(R.string.media_move_up, media.filename))
                        }
                        IconButton(onClick = { onReorder(moveMedia(order, id, order[index + 1], true)) }, enabled = !blocked && index < order.lastIndex, modifier = Modifier.testTag("media-down-$id")) {
                            Icon(Icons.Default.KeyboardArrowDown, contentDescription = stringResource(R.string.media_move_down, media.filename))
                        }
                    }
                    Text(stringResource(R.string.media_clip_duration, media.effectiveDuration?.let(::seconds) ?: stringResource(R.string.media_unknown_duration)) +
                        if (editor.isDirty(id)) " · ${stringResource(R.string.media_card_draft)}" else "", style = MaterialTheme.typography.bodySmall)
                    if (!previewEnabled) Text(stringResource(R.string.offline_media), style = MaterialTheme.typography.bodySmall)
                    else if (opened != id) {
                        Box(Modifier.fillMaxWidth().height(112.dp).testTag("media-preview-$id")
                            .clickable { previewed = id }.semantics { contentDescription = media.filename }, contentAlignment = Alignment.Center) {
                            val thumbnail = if (media.isVideo) media.thumbnailUrl else media.previewUrl
                            if (thumbnail == null) Text(stringResource(R.string.media_preview_missing))
                            else key(thumbnail) { RemoteMediaPreview(thumbnail, false, media.filename, onPreview) }
                        }
                    }
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        if (media.isVideo) MediaIconAction(stringResource(R.string.media_edit_trim), if (opened == id) Icons.Default.Close else Icons.Default.Edit, !busy, Modifier.testTag("media-edit-$id")) { opened = if (opened == id) null else id }
                        MediaIconAction(stringResource(R.string.media_save), Icons.Default.Check, !blocked && editor.canSave(id), Modifier.testTag("media-save-$id")) { onSave(id) }
                        MediaIconAction(stringResource(R.string.media_discard), Icons.Default.Refresh, canResolve && !busy && editor.isDirty(id) && !(editor.readRequired && editor.issue in setOf(EditorIssue.READ, EditorIssue.UNCERTAIN)), Modifier.testTag("media-discard-$id")) { onDiscard(id) }
                        MediaIconAction(stringResource(R.string.media_remove), Icons.Default.Delete, !blocked, Modifier.testTag("media-remove-$id")) { if (editor.isDirty(id)) removing = id else onRemove(id, false) }
                    }
                    if (opened == id) {
                        if (previewEnabled && media.originalUrl != null) key(media.originalUrl) {
                            RemoteMediaPreview(media.originalUrl, true, media.filename, onPreview, contentType = media.contentType)
                        }
                        media.sectionPreview?.takeUnless { it.status == "missing" }?.let { preview ->
                            Text(stringResource(R.string.media_section_preview), style = MaterialTheme.typography.titleSmall)
                            if (editor.isDirty(id)) Text(stringResource(R.string.media_preview_draft_warning))
                            Text(stringResource(when (preview.status) {
                                "ready" -> R.string.media_render_ready
                                "queued" -> R.string.media_render_queued
                                "processing" -> R.string.media_render_processing
                                else -> R.string.media_render_failed
                            }), modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
                            if (preview.status == "ready" && preview.url != null && previewEnabled) key(preview.generation) {
                                RemoteMediaPreview(preview.url, true, stringResource(R.string.media_section_preview), onPreview)
                            }
                            if (preview.status == "failed") MediaIconAction(stringResource(R.string.retry), Icons.Default.Refresh, !blocked) { onRetryPreview(id) }
                        }
                        val rows = editor.inputs[id].orEmpty()
                        val ranges = parseRanges(rows, media.sourceDuration)
                        if (media.sourceDuration != null && ranges != null) MediaRangeTimeline(media.sourceDuration, ranges, blocked) { changed ->
                            onEditRanges(id, changed.map { RangeInput(it.start.toString(), it.end.toString()) })
                        }
                        VideoRangeFields(media, rows, blocked) { onEditRanges(id, it) }
                    }
                    if (!media.isVideo) OutlinedTextField(editor.inputs[id]?.firstOrNull()?.end.orEmpty(), { onPhotoDuration(id, it) },
                        label = { Text(stringResource(R.string.media_photo_duration)) }, singleLine = true, enabled = !blocked,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.testTag("photo-duration-$id"))
                    if (editor.isDirty(id) && !editor.canSave(id)) Text(stringResource(if (editor.readRequired) R.string.media_changed else R.string.media_invalid),
                        modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
                    if (after) HorizontalDivider(thickness = 3.dp, color = MaterialTheme.colorScheme.primary, modifier = Modifier.testTag("media-insertion-$id-after"))
                }
            } }
            val removed = snapshot.media.filter { it.status == "removed" }
            if (ordered.isEmpty()) Text(stringResource(R.string.media_empty))
            if (removed.isNotEmpty()) {
                SectionHeading(R.string.media_removed)
                Text(stringResource(R.string.media_removed_help), style = MaterialTheme.typography.bodySmall)
                removed.forEach { media ->
                    Text(media.filename, style = MaterialTheme.typography.titleMedium)
                    OutlinedButton(onClick = { onRestore(media.mediaId) }, enabled = !blocked, modifier = Modifier.testTag("media-restore-${media.mediaId}")) { Text(stringResource(R.string.media_restore)) }
                }
            }
            Text(stringResource(R.string.media_total, total?.let(::seconds) ?: stringResource(R.string.media_unknown_duration), seconds(snapshot.montage.maxDurationSeconds)),
                modifier = Modifier.testTag("media-duration").semantics { liveRegion = LiveRegionMode.Polite })
            if (total == null) Text(stringResource(R.string.media_duration_help), color = MaterialTheme.colorScheme.error)
            if (total != null && total > snapshot.montage.maxDurationSeconds) Text(stringResource(R.string.media_limit_help, seconds(total - snapshot.montage.maxDurationSeconds)), color = MaterialTheme.colorScheme.error)
            if (snapshot.renderStale) Text(stringResource(R.string.media_render_stale), style = MaterialTheme.typography.bodySmall)
            Text(stringResource(if (editor.dirty) R.string.media_unsaved else R.string.media_saved), style = MaterialTheme.typography.bodySmall)
        }
    }
    removing?.let { id -> AlertDialog(onDismissRequest = { removing = null },
        title = { Text(stringResource(R.string.media_remove)) }, text = { Text(stringResource(R.string.media_remove_draft)) },
        confirmButton = { TextButton(onClick = { removing = null; onRemove(id, true) }) { Text(stringResource(R.string.media_remove)) } },
        dismissButton = { TextButton(onClick = { removing = null }) { Text(stringResource(R.string.cancel)) } }) }
    if (clearing) AlertDialog(onDismissRequest = { clearing = false }, title = { Text(stringResource(R.string.media_clear)) },
        text = { Text("${pendingClearFolder ?: snapshot?.`package`?.folderName.orEmpty()}\n${stringResource(R.string.media_clear_warning)}") },
        confirmButton = { TextButton(onClick = { clearing = false; onClear(true) }) { Text(stringResource(R.string.media_clear)) } },
        dismissButton = { TextButton(onClick = { clearing = false }) { Text(stringResource(R.string.cancel)) } })
    if (previewEnabled) previewed?.let { id -> byId[id]?.let { media -> key(media.mediaId, snapshot?.contentRevision) {
        MediaFullscreenDialog(media, { previewed = null }, onPreview)
    } } }
}

@Composable private fun VideoRangeFields(media: EditorMediaOut, rows: List<RangeInput>, blocked: Boolean, onChange: (List<RangeInput>) -> Unit) {
    val duration = media.sourceDuration?.takeIf { it.isFinite() && it > 0 }
    if (duration == null) { Text(stringResource(R.string.media_duration_help)); return }
    val invalid = rows.isNotEmpty() && parseRanges(rows, duration) == null
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(stringResource(if (rows.isEmpty()) R.string.range_whole else R.string.range_selected))
        Text(stringResource(R.string.range_source, seconds(duration)), style = MaterialTheme.typography.bodySmall)
        rows.forEachIndexed { index, row ->
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text(stringResource(R.string.range_number, index + 1), style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
                MediaIconAction(stringResource(R.string.range_remove, index + 1), Icons.Default.Delete, !blocked) { onChange(rows.filterIndexed { i, _ -> i != index }) }
            }
            OutlinedTextField(row.start, { value -> onChange(rows.mapIndexed { i, r -> if (i == index) r.copy(start = value) else r }) },
                label = { Text(stringResource(R.string.range_start)) }, enabled = !blocked, isError = invalid, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.fillMaxWidth().testTag("range-start-${media.mediaId}-$index"))
            OutlinedTextField(row.end, { value -> onChange(rows.mapIndexed { i, r -> if (i == index) r.copy(end = value) else r }) },
                label = { Text(stringResource(R.string.range_end)) }, enabled = !blocked, isError = invalid, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.fillMaxWidth().testTag("range-end-${media.mediaId}-$index"))
        }
        if (invalid) Text(stringResource(R.string.media_invalid), color = MaterialTheme.colorScheme.error,
            modifier = Modifier.testTag("range-error-${media.mediaId}").semantics { liveRegion = LiveRegionMode.Polite })
        OutlinedButton(onClick = { onChange(rows + RangeInput("", "")) }, enabled = !blocked, modifier = Modifier.testTag("range-add-${media.mediaId}")) { Text(stringResource(R.string.range_add)) }
        TextButton(onClick = { onChange(emptyList()) }, enabled = !blocked && rows.isNotEmpty()) { Text(stringResource(R.string.range_reset)) }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable private fun MediaIconAction(label: String, image: ImageVector, enabled: Boolean,
    modifier: Modifier = Modifier, onClick: () -> Unit) {
    TooltipBox(positionProvider = TooltipDefaults.rememberPlainTooltipPositionProvider(),
        tooltip = { PlainTooltip { Text(label) } }, state = rememberTooltipState()) {
        IconButton(onClick = onClick, enabled = enabled, modifier = modifier) { Icon(image, label) }
    }
}

@Composable internal fun RemoteMediaPreview(previewUrl: String, isVideo: Boolean, label: String, load: suspend (String, File) -> Unit,
    contentType: String? = null, onDuration: (Double) -> Unit = {}, mediaModifier: Modifier? = null) {
    val context = LocalContext.current
    val loader by rememberUpdatedState(load)
    var attempt by remember { mutableIntStateOf(0) }
    var image by remember(attempt) { mutableStateOf<Bitmap?>(null) }
    var video by remember(attempt) { mutableStateOf<File?>(null) }
    var loading by remember(attempt) { mutableStateOf(true) }
    var failed by remember(attempt) { mutableStateOf(false) }
    DisposableEffect(image) {
        val bitmap = image
        onDispose { bitmap?.recycle() }
    }
    LaunchedEffect(previewUrl, attempt) {
        var file: File? = null
        try {
            val temporary = withContext(Dispatchers.IO) {
                val directory = context.cacheDir.resolve("media-previews")
                check(directory.isDirectory || directory.mkdirs())
                val suffix = if (!isVideo) ".jpg" else when (contentType) { "video/quicktime" -> ".mov"; "video/webm" -> ".webm"; else -> ".mp4" }
                File.createTempFile("media-", suffix, directory).also { file = it }
            }
            loader(previewUrl, temporary)
            ensureActive()
            if (isVideo) video = temporary
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
            }
            awaitCancellation()
        } catch (e: CancellationException) {
            currentCoroutineContext().ensureActive()
            failed = true; loading = false
        }
        catch (_: Exception) { failed = true; loading = false }
        finally { file?.delete() }
    }
    image?.let { Image(it.asImageBitmap(), contentDescription = label, modifier = mediaModifier ?: Modifier.fillMaxWidth().heightIn(max = 240.dp)) }
    video?.let { file -> key(file) {
        NativeVideo(file, label, { loading = false }, { file.delete(); failed = true; loading = false; video = null }, onDuration,
            modifier = mediaModifier ?: Modifier.fillMaxWidth().height(240.dp))
    } }
    if (loading && !failed) Text(stringResource(R.string.media_preview_loading),
        modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
    if (failed) {
        Text(stringResource(R.string.media_preview_failed), color = MaterialTheme.colorScheme.error,
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
        TextButton(onClick = { attempt++ }) { Text(stringResource(R.string.retry)) }
    }
}
