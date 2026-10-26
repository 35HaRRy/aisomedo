package com.dojo.aisomedo.ui

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.media.MediaMetadataRetriever
import android.net.Uri
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** Local image thumbnail, or a video cover frame. Preview failures stay silent. */
@Composable
internal fun MediaThumbnail(
    uri: Uri,
    contentType: String?,
    label: String,
    modifier: Modifier = Modifier,
    maxHeight: Dp = 180.dp,
) {
    val context = LocalContext.current
    var bitmap by remember(uri, contentType) { mutableStateOf<Bitmap?>(null) }
    LaunchedEffect(uri, contentType) {
        bitmap = withContext(Dispatchers.IO) { runCatching { loadThumbnail(context, uri, contentType) }.getOrNull() }
    }
    bitmap?.let { Image(it.asImageBitmap(), contentDescription = label, contentScale = ContentScale.Fit,
        modifier = modifier.fillMaxWidth().heightIn(max = maxHeight)) }
}

private fun loadThumbnail(context: Context, uri: Uri, contentType: String?): Bitmap? {
    val resolver = context.contentResolver
    if ((contentType ?: resolver.getType(uri)).orEmpty().startsWith("video/")) {
        val retriever = MediaMetadataRetriever()
        return try {
            retriever.setDataSource(context, uri)
            retriever.getFrameAtTime(0, MediaMetadataRetriever.OPTION_CLOSEST_SYNC)
        } finally { retriever.release() }
    }
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    resolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds) }
    if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
    val options = BitmapFactory.Options().apply {
        inSampleSize = 1
        while (maxOf(bounds.outWidth, bounds.outHeight) / inSampleSize > 1024) inSampleSize *= 2
    }
    return resolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, options) }
}
