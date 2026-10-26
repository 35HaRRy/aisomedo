package com.dojo.aisomedo.ui

import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.key
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.dojo.aisomedo.R
import com.dojo.aisomedo.api.EditorMediaOut
import java.io.File

@Composable fun MediaFullscreenDialog(media: EditorMediaOut, onDismiss: () -> Unit, load: suspend (String, File) -> Unit) {
    Dialog(onDismissRequest = onDismiss, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize()) {
            Column(Modifier.fillMaxSize().systemBarsPadding().padding(16.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                Row(Modifier.fillMaxWidth()) {
                    Text(media.filename, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
                    IconButton(onClick = onDismiss) { Icon(Icons.Default.Close, stringResource(R.string.media_close_fullscreen)) }
                }
                val source = if (media.isVideo) media.originalUrl else media.previewUrl
                if (source == null) Text(stringResource(R.string.media_preview_missing))
                else key(source) { RemoteMediaPreview(source, media.isVideo, media.filename, load, contentType = media.contentType,
                    mediaModifier = Modifier.fillMaxWidth().weight(1f)) }
            }
        }
    }
}
