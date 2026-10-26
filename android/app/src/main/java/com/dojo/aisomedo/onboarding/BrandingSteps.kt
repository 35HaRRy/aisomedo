package com.dojo.aisomedo.onboarding

import android.graphics.BitmapFactory
import android.net.Uri
import android.media.MediaMetadataRetriever
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.dojo.aisomedo.AppViewModel
import com.dojo.aisomedo.R
import com.dojo.aisomedo.api.readBounded
import com.dojo.aisomedo.ui.MediaThumbnail
import kotlinx.coroutines.*
import java.io.InputStream

fun readBrandingImage(input: InputStream): ByteArray = readBounded(input, 10 * 1024 * 1024)

@Composable fun BrandingSteps(model: AppViewModel, cards: Boolean, onboarding: Boolean = true) {
    val state by model.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var reading by remember { mutableStateOf(false) }
    var selectedField by rememberSaveable { mutableStateOf("logo_asset") }
    var selectionBinding by rememberSaveable { mutableStateOf<String?>(null) }
    var selectedUri by rememberSaveable { mutableStateOf<String?>(null) }
    var selectedUriField by rememberSaveable { mutableStateOf<String?>(null) }
    val step = if (cards) "cards" else "logo"
    val access = state.canConfigure(step)
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null && selectionBinding != null && selectionBinding == model.currentBinding) scope.launch {
            val field = selectedField
            val binding = selectionBinding
            selectedUri = uri.toString(); selectedUriField = field
            reading = true
            try {
                val bytes = withContext(Dispatchers.IO) {
                    val types = if (field == "logo_asset") listOf("image/png", "image/jpeg") else cardMediaTypes
                    require(context.contentResolver.getType(uri) in types)
                    context.contentResolver.openInputStream(uri)?.use(::readBrandingImage) ?: throw IllegalArgumentException("document")
                }
                model.uploadAsset(field, bytes, binding)
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) { model.pickerFailed() }
            finally { reading = false }
        }
    }
    val fields = if (cards) listOf("intro_asset", "outro_asset") else listOf("logo_asset")
    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
        if (cards) {
            StepHeading(R.string.cards) {
                Button(onClick = {
                    val branding = state.branding ?: return@Button
                    model.saveCards(branding.introAsset, if (branding.introAsset != null) state.drafts["intro_duration"]?.toDoubleOrNull() else null,
                        branding.outroAsset, if (branding.outroAsset != null) state.drafts["outro_duration"]?.toDoubleOrNull() else null)
                }, enabled = access && !reading && state.branding != null) { Text(stringResource(R.string.save_cards)) }
                if (onboarding) TextButton(onClick = model::skipCards, enabled = access && !reading) { Text(stringResource(R.string.skip_cards)) }
            }
        }
        Text(stringResource(if (cards) R.string.card_media_help else R.string.branding_help))
        if (reading || state.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
        fields.forEach { field ->
            val label = when (field) { "intro_asset" -> R.string.intro_card; "outro_asset" -> R.string.outro_card; else -> R.string.logo }
            val asset = when (field) { "intro_asset" -> state.branding?.introAsset; "outro_asset" -> state.branding?.outroAsset; else -> state.branding?.logoAsset }
            StepHeading(label, leading = {
                if (cards && (asset != null || selectedUriField == field && selectedUri != null || field in state.pendingAssets)) IconButton(onClick = {
                    if (selectedUriField == field) { selectedUri = null; selectedUriField = null }
                    model.clearCard(field)
                }, enabled = access && !reading) { Icon(Icons.Default.Delete, contentDescription = stringResource(R.string.clear_named_card, stringResource(label))) }
            }) {
                Button(onClick = { selectedField = field; selectionBinding = model.currentBinding; picker.launch(if (cards) cardMediaTypes.toTypedArray() else arrayOf("image/png", "image/jpeg")) }, enabled = !reading && access) { Text(stringResource(if (cards) R.string.choose_card_media else R.string.choose_image)) }
                if (field in state.pendingAssets) OutlinedButton(onClick = { model.retryAsset(field) }, enabled = access && !reading) { Text(stringResource(R.string.retry_asset)) }
            }
            asset?.let { if (state.networkConnected) BrandingPreview(model, it, label) else Text(stringResource(R.string.offline_media)) }
            if (selectedUriField == field) selectedUri?.let { value ->
                val selected = Uri.parse(value)
                MediaThumbnail(selected, context.contentResolver.getType(selected),
                    stringResource(R.string.selected_image_preview, stringResource(label)), maxHeight = 200.dp)
            }
            if (cards) {
                val key = field.replace("_asset", "_duration")
                OutlinedTextField(state.drafts[key].orEmpty(), { value -> if (value.isEmpty() || value.matches(Regex("[1-9][0-9]*")) && value.toLongOrNull() != null) model.setDraft(key, value, "cards") }, label = { Text(stringResource(R.string.card_duration)) }, singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    enabled = state.networkConnected && state.authoritative && step in state.configurationFresh, modifier = Modifier.fillMaxWidth())
            }
            if (field in state.pendingAssets) {
                Text(stringResource(R.string.upload_pending))
            }
        }
    }
}
private val cardMediaTypes = listOf("image/png", "image/jpeg", "video/mp4", "video/quicktime", "video/webm", "video/x-matroska", "video/x-msvideo")

@Composable private fun BrandingPreview(model: AppViewModel, asset: String, label: Int) {
    val context = LocalContext.current
    var bitmap by remember(asset) { mutableStateOf<android.graphics.Bitmap?>(null) }
    var failed by remember(asset) { mutableStateOf(false) }
    var retry by remember(asset) { mutableIntStateOf(0) }
    LaunchedEffect(asset, retry) {
        try {
            failed = false
            require(asset.startsWith("branding/assets/"))
            val bytes = model.preview("/api/settings/branding/assets/" + asset.removePrefix("branding/assets/"))
            bitmap = withContext(Dispatchers.Default) {
                if (asset.substringAfterLast('.') in setOf("mp4", "mov", "webm", "mkv", "avi")) {
                    val temporary = withContext(Dispatchers.IO) { java.io.File.createTempFile("card-preview-", ".video", context.cacheDir).apply { writeBytes(bytes) } }
                    val retriever = MediaMetadataRetriever()
                    try {
                        retriever.setDataSource(temporary.absolutePath)
                        retriever.getScaledFrameAtTime(0, MediaMetadataRetriever.OPTION_CLOSEST_SYNC, 512, 512)
                    } finally { retriever.release(); temporary.delete() }
                } else {
                val options = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options)
                require(options.outWidth in 1..4096 && options.outHeight in 1..4096)
                options.inJustDecodeBounds = false
                options.inSampleSize = 1
                while (maxOf(options.outWidth, options.outHeight) / options.inSampleSize > 1024) options.inSampleSize *= 2
                BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options) ?: throw IllegalArgumentException("image")
                }
            }
        } catch (e: CancellationException) { throw e }
        catch (_: Exception) { failed = true }
    }
    bitmap?.let { Image(it.asImageBitmap(), contentDescription = stringResource(R.string.image_preview, stringResource(label)), modifier = Modifier.fillMaxWidth().heightIn(max = 200.dp)) }
    if (failed) {
        Text(stringResource(R.string.preview_failed))
        StepHeading(label) { TextButton(onClick = { retry++ }) { Text(stringResource(R.string.retry)) } }
    }
}
