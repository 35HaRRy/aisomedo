package com.dojo.aisomedo.ui

import androidx.activity.compose.BackHandler
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
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.LayoutCoordinates
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.*
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.dojo.aisomedo.R
import com.dojo.aisomedo.api.EditorMediaOut
import com.dojo.aisomedo.editor.*
import kotlinx.coroutines.delay
import java.util.Locale

private data class DropTarget(val id: String, val after: Boolean)
private fun seconds(value: Double) = String.format(Locale.ROOT, "%.2f", value)

@OptIn(ExperimentalLayoutApi::class)
@Composable fun MediaEditorPanel(
    editor: MediaEditorState, busy: Boolean, scroll: ScrollState, viewport: Rect,
    onRefresh: () -> Unit, onReorder: (List<String>) -> Unit, onRemove: (String) -> Unit, onRestore: (String) -> Unit,
    onEditRanges: (String, List<RangeInput>) -> Unit, onSave: () -> Unit, onDiscard: () -> Unit,
) {
    val snapshot = editor.snapshot
    val blocked = busy || editor.readRequired || snapshot?.`package`?.status == "completed"
    val order = snapshot?.montage?.order.orEmpty()
    val byId = snapshot?.media.orEmpty().associateBy { it.mediaId }
    val ordered = order.mapNotNull(byId::get).filter { it.status == "finalized" }
    val bounds = remember { mutableMapOf<String, Rect>() }
    var dragged by remember { mutableStateOf<String?>(null) }
    var pointer by remember { mutableStateOf(Offset.Zero) }
    var target by remember { mutableStateOf<DropTarget?>(null) }
    var opened by rememberSaveable(snapshot?.`package`?.folderName) { mutableStateOf<String?>(null) }
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
    Column(Modifier.widthIn(max = 640.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        SectionHeading(R.string.media_management)
        OutlinedButton(onClick = onRefresh, enabled = !busy) { Text(stringResource(R.string.refresh)) }
        editor.issue?.let { issue -> Text(stringResource(when (issue) {
            EditorIssue.READ -> R.string.media_read_failed; EditorIssue.CONFLICT -> R.string.media_changed
            EditorIssue.INVALID -> R.string.media_invalid; EditorIssue.LIMIT -> R.string.media_limit_failed
            EditorIssue.UNCERTAIN -> R.string.media_uncertain
        }), color = MaterialTheme.colorScheme.error, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Assertive }) }
        if (snapshot == null) Text(stringResource(if (busy) R.string.loading else R.string.media_no_active))
        else {
            val total = editor.proposedTotal
            Text(stringResource(R.string.media_total, total?.let(::seconds) ?: stringResource(R.string.media_unknown_duration), seconds(snapshot.montage.maxDurationSeconds)),
                modifier = Modifier.testTag("media-duration").semantics { liveRegion = LiveRegionMode.Polite })
            if (total == null) Text(stringResource(R.string.media_duration_help), color = MaterialTheme.colorScheme.error)
            if (total != null && total > snapshot.montage.maxDurationSeconds) Text(
                stringResource(R.string.media_limit_help, seconds(total - snapshot.montage.maxDurationSeconds)), color = MaterialTheme.colorScheme.error)
            if (snapshot.renderStale) Text(stringResource(R.string.media_render_stale), style = MaterialTheme.typography.bodySmall)
            Text(stringResource(if (editor.dirty) R.string.media_unsaved else R.string.media_saved), style = MaterialTheme.typography.bodySmall)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onSave, enabled = !blocked && editor.canSave, modifier = Modifier.testTag("media-save")) { Text(stringResource(R.string.media_save)) }
                TextButton(onClick = onDiscard, enabled = !busy && editor.dirty) { Text(stringResource(R.string.media_discard)) }
            }
            Text(stringResource(R.string.media_drag_help), style = MaterialTheme.typography.bodySmall)
            ordered.forEachIndexed { index, media -> key(media.mediaId) {
                val id = media.mediaId
                var handle by remember { mutableStateOf<LayoutCoordinates?>(null) }
                val before = target == DropTarget(id, false)
                val after = target == DropTarget(id, true)
                Column(Modifier.fillMaxWidth().testTag("media-row-$id")
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
                        Text(stringResource(R.string.media_position, index + 1, media.filename), style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                        IconButton(onClick = { onReorder(moveMedia(order, id, order[index - 1], false)) }, enabled = !blocked && index > 0, modifier = Modifier.testTag("media-up-$id")) {
                            Icon(Icons.Default.KeyboardArrowUp, contentDescription = stringResource(R.string.media_move_up, media.filename))
                        }
                        IconButton(onClick = { onReorder(moveMedia(order, id, order[index + 1], true)) }, enabled = !blocked && index < order.lastIndex, modifier = Modifier.testTag("media-down-$id")) {
                            Icon(Icons.Default.KeyboardArrowDown, contentDescription = stringResource(R.string.media_move_down, media.filename))
                        }
                    }
                    Text(stringResource(R.string.media_clip_duration, media.effectiveDuration?.let(::seconds) ?: stringResource(R.string.media_unknown_duration)), style = MaterialTheme.typography.bodySmall)
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        if (media.isVideo) OutlinedButton(onClick = { opened = if (opened == id) null else id }, enabled = !busy, modifier = Modifier.testTag("media-edit-$id")) { Text(stringResource(R.string.media_edit_trim)) }
                        TextButton(onClick = { onRemove(id) }, enabled = !blocked, modifier = Modifier.testTag("media-remove-$id")) { Text(stringResource(R.string.media_remove)) }
                    }
                    if (opened == id) VideoRangeFields(media, editor.inputs[id].orEmpty(), blocked) { onEditRanges(id, it) }
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
        }
    }
}

@Composable private fun VideoRangeFields(media: EditorMediaOut, rows: List<RangeInput>, blocked: Boolean, onChange: (List<RangeInput>) -> Unit) {
    val duration = media.sourceDuration?.takeIf { it.isFinite() && it > 0 }
    if (duration == null) { Text(stringResource(R.string.media_duration_help)); return }
    val invalid = rows.isNotEmpty() && parseRanges(rows, duration) == null
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(stringResource(if (rows.isEmpty()) R.string.range_whole else R.string.range_selected))
        Text(stringResource(R.string.range_source, seconds(duration)), style = MaterialTheme.typography.bodySmall)
        rows.forEachIndexed { index, row ->
            Text(stringResource(R.string.range_number, index + 1), style = MaterialTheme.typography.titleSmall)
            OutlinedTextField(row.start, { value -> onChange(rows.mapIndexed { i, r -> if (i == index) r.copy(start = value) else r }) },
                label = { Text(stringResource(R.string.range_start)) }, enabled = !blocked, isError = invalid, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.fillMaxWidth().testTag("range-start-${media.mediaId}-$index"))
            OutlinedTextField(row.end, { value -> onChange(rows.mapIndexed { i, r -> if (i == index) r.copy(end = value) else r }) },
                label = { Text(stringResource(R.string.range_end)) }, enabled = !blocked, isError = invalid, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.fillMaxWidth().testTag("range-end-${media.mediaId}-$index"))
            TextButton(onClick = { onChange(rows.filterIndexed { i, _ -> i != index }) }, enabled = !blocked) { Text(stringResource(R.string.range_remove, index + 1)) }
        }
        if (invalid) Text(stringResource(R.string.media_invalid), color = MaterialTheme.colorScheme.error,
            modifier = Modifier.testTag("range-error-${media.mediaId}").semantics { liveRegion = LiveRegionMode.Polite })
        OutlinedButton(onClick = { onChange(rows + RangeInput("", "")) }, enabled = !blocked, modifier = Modifier.testTag("range-add-${media.mediaId}")) { Text(stringResource(R.string.range_add)) }
        TextButton(onClick = { onChange(emptyList()) }, enabled = !blocked && rows.isNotEmpty()) { Text(stringResource(R.string.range_reset)) }
    }
}
