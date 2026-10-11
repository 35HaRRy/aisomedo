package com.dojo.aisomedo.reviews

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import com.dojo.aisomedo.R
import com.dojo.aisomedo.api.ReviewDetailOut
import com.dojo.aisomedo.ui.NativeVideo
import kotlinx.coroutines.*
import java.io.File

@Composable fun ReviewPreview(detail: ReviewDetailOut, onDownload: suspend (Int, String, File) -> Unit, onReady: (Int, String, Boolean) -> Unit) {
    val review = detail.review
    key(review.id, review.revisionDigest, review.version, detail.renderReady, detail.previewUrl) {
        val context = LocalContext.current
        val download by rememberUpdatedState(onDownload)
        val ready by rememberUpdatedState(onReady)
        var attempt by remember { mutableIntStateOf(0) }
        var file by remember(attempt) { mutableStateOf<File?>(null) }
        var failed by remember(attempt) { mutableStateOf(false) }
        var loading by remember(attempt) { mutableStateOf(true) }
        fun revoke() { ready(review.id, review.revisionDigest, false) }
        DisposableEffect(review.id, review.revisionDigest) {
            onDispose { revoke(); file?.delete() }
        }
        LaunchedEffect(attempt) {
            var owned: File? = null
            try {
                revoke()
                if (!detail.renderReady || detail.previewUrl == null) return@LaunchedEffect
                owned = withContext(Dispatchers.IO) {
                    val directory = File(context.cacheDir, "review-previews").apply { mkdirs() }
                    File.createTempFile("review-", ".mp4", directory)
                }
                download(review.id, review.revisionDigest, owned)
                ensureActive()
                file = owned; loading = false
                awaitCancellation()
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) { failed = true; loading = false; revoke() }
            finally { revoke(); owned?.delete() }
        }
        if (detail.renderReady) {
            if (loading) LinearProgressIndicator(Modifier.fillMaxWidth().testTag("review-preview-loading"))
            file?.takeUnless { failed }?.let { local ->
                NativeVideo(local, stringResource(R.string.review_player),
                    { ready(review.id, review.revisionDigest, true) },
                    { revoke(); local.delete(); failed = true })
            }
            if (failed) {
                Text(stringResource(R.string.review_preview_error), color = MaterialTheme.colorScheme.error, modifier = Modifier.testTag("review-preview-error"))
                TextButton(onClick = { revoke(); file?.delete(); attempt++ }) { Text(stringResource(R.string.retry)) }
            }
        }
    }
}
