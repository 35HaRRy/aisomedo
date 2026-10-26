package com.dojo.aisomedo.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.res.stringResource
import com.dojo.aisomedo.AppUiState
import com.dojo.aisomedo.R
import com.dojo.aisomedo.api.PackageArtifactOut
import java.io.File

@Composable fun CompletedPackagesScreen(state: AppUiState, onSelect: (String) -> Unit,
    onRefresh: () -> Unit, onPreview: suspend (String, File) -> Unit) {
    Heading(R.string.completed_packages)
    Text(stringResource(R.string.completed_read_only))
    OutlinedButton(onClick = onRefresh, enabled = !state.busy && state.networkConnected) { Text(stringResource(R.string.refresh)) }
    if (state.completedError) Text(stringResource(R.string.completed_error), color = MaterialTheme.colorScheme.error)
    val packages = state.completedPackages
    if (packages == null && !state.completedError) Text(stringResource(R.string.loading))
    if (packages?.isEmpty() == true) Text(stringResource(R.string.completed_empty))
    if (!packages.isNullOrEmpty()) {
        var choosing by remember { mutableStateOf(false) }
        Text(stringResource(R.string.completed_choose))
        Box {
            OutlinedButton(onClick = { choosing = true }, enabled = !state.busy) {
                Text(state.completedFolder ?: stringResource(R.string.completed_choose))
            }
            DropdownMenu(expanded = choosing, onDismissRequest = { choosing = false }) {
                packages.forEach { item -> DropdownMenuItem(text = { Text(item.folderName) },
                    onClick = { choosing = false; onSelect(item.folderName) }) }
            }
        }
    }
    val detail = state.completedDetail
    if (state.completedFolder != null && detail == null && !state.completedError) Text(stringResource(R.string.loading))
    if (detail != null) key(detail.folderName) {
        CollapsiblePanel(detail.folderName) {
            detail.caption?.let { SelectionContainer { Text(it) } }
            CompletedArtifacts(detail.artifacts, state.networkConnected && state.authoritative, onPreview)
            val positions = detail.order.withIndex().associate { it.value to it.index }
            detail.media.sortedBy { positions[it.mediaId] ?: Int.MAX_VALUE }.forEach { media -> key(media.mediaId) {
                CollapsiblePanel(media.filename) {
                    if (media.status == "removed") Text(stringResource(R.string.media_removed))
                    CompletedArtifacts(media.artifacts, state.networkConnected && state.authoritative, onPreview)
                }
            } }
        }
    }
}

@Composable private fun CompletedArtifacts(artifacts: List<PackageArtifactOut>, previewEnabled: Boolean,
    onPreview: suspend (String, File) -> Unit) {
    artifacts.forEach { artifact -> key(artifact.artifactRef) {
        var opened by rememberSaveable { mutableStateOf(artifact.kind == "render") }
        if (!artifact.available) Text(stringResource(R.string.completed_file_missing, artifact.filename))
        else {
            Text(artifact.filename, style = MaterialTheme.typography.titleSmall)
            if (!previewEnabled) Text(stringResource(R.string.offline_media))
            else artifact.previewUrl?.let { url ->
                TextButton(onClick = { opened = !opened }) {
                    Text(stringResource(if (opened) R.string.media_preview_hide else R.string.media_preview_show))
                }
                if (opened) key(url) { RemoteMediaPreview(url, artifact.contentType.startsWith("video/"),
                    stringResource(R.string.completed_preview, artifact.filename), onPreview) }
            }
        }
    } }
}
