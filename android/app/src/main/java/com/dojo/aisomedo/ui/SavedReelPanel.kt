package com.dojo.aisomedo.ui

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import com.dojo.aisomedo.R
import com.dojo.aisomedo.editor.MediaEditorState
import java.io.File
import java.util.Locale

@Composable fun SavedReelPanel(editor: MediaEditorState, enabled: Boolean, onRender: () -> Unit, load: suspend (String, File) -> Unit) {
    val snapshot = editor.snapshot ?: return
    val ready = snapshot.renderStatus == "ready" && snapshot.renderPreviewUrl != null
    var metadata by remember(snapshot.renderPreviewUrl) { mutableStateOf<Double?>(null) }
    val duration = snapshot.renderDuration ?: metadata
    val suffix = if (!ready) stringResource(R.string.media_not_rendered) else duration?.let { String.format(Locale.ROOT, "%.2f s", it) } ?: stringResource(R.string.media_unknown_duration)
    CollapsiblePanel("${stringResource(R.string.media_saved_reel)} · $suffix", Modifier.testTag("saved-reel-panel"), actions = {
        IconButton(onClick = onRender, enabled = enabled && snapshot.montage.order.isNotEmpty() && snapshot.montage.durationComplete && !snapshot.montage.overLimit && snapshot.renderStatus !in setOf("queued", "processing")) {
            Icon(Icons.Default.PlayArrow, stringResource(R.string.media_render))
        }
    }) {
        if (editor.dirty) Text(stringResource(R.string.media_preview_draft_warning))
        Text(stringResource(when (snapshot.renderStatus) {
            "queued" -> R.string.media_render_queued
            "processing" -> R.string.media_render_processing
            "failed" -> R.string.media_render_failed
            "stale" -> R.string.media_render_stale
            "ready" -> R.string.media_render_ready
            else -> R.string.media_not_rendered_body
        }))
        if (ready) key(snapshot.renderPreviewUrl) {
            RemoteMediaPreview(snapshot.renderPreviewUrl!!, true, stringResource(R.string.media_saved_reel), load,
                onDuration = { metadata = it })
        }
    }
}
