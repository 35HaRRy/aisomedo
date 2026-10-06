package com.dojo.aisomedo.onboarding

import android.graphics.BitmapFactory
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.dojo.aisomedo.AppViewModel
import com.dojo.aisomedo.R
import com.dojo.aisomedo.api.readBounded
import kotlinx.coroutines.*
import java.io.InputStream

fun readBrandingImage(input: InputStream): ByteArray = readBounded(input, 10 * 1024 * 1024)

@Composable fun BrandingSteps(model: AppViewModel, cards: Boolean) {
    val state by model.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var reading by remember { mutableStateOf(false) }
    var selectedField by remember { mutableStateOf("logo_asset") }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) scope.launch {
            reading = true
            try {
                val bytes = withContext(Dispatchers.IO) {
                    require(context.contentResolver.getType(uri) in listOf("image/png", "image/jpeg"))
                    context.contentResolver.openInputStream(uri)?.use(::readBrandingImage) ?: throw IllegalArgumentException("document")
                }
                model.uploadAsset(selectedField, bytes)
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) { model.pickerFailed() }
            finally { reading = false }
        }
    }
    val fields = if (cards) listOf("intro_asset", "outro_asset") else listOf("logo_asset")
    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text(stringResource(R.string.branding_help))
        if (reading) LinearProgressIndicator(Modifier.fillMaxWidth())
        fields.forEach { field ->
            val label = when (field) { "intro_asset" -> R.string.intro_card; "outro_asset" -> R.string.outro_card; else -> R.string.logo }
            val asset = when (field) { "intro_asset" -> state.branding?.introAsset; "outro_asset" -> state.branding?.outroAsset; else -> state.branding?.logoAsset }
            SectionHeadingForBranding(label)
            asset?.let { BrandingPreview(model, it, label) }
            if (cards) {
                val key = field.replace("_asset", "_duration")
                OutlinedTextField(state.drafts[key].orEmpty(), { model.setDraft(key, it, "cards") }, label = { Text(stringResource(R.string.card_duration)) }, singleLine = true)
            }
            Button(onClick = { selectedField = field; picker.launch(arrayOf("image/png", "image/jpeg")) }, enabled = !reading && !state.busy) { Text(stringResource(R.string.choose_image)) }
            if (field in state.pendingAssets) {
                Text(stringResource(R.string.upload_pending))
                OutlinedButton(onClick = { model.retryAsset(field) }, enabled = !state.busy && !reading) { Text(stringResource(R.string.retry_asset)) }
            }
            if (cards && asset != null) OutlinedButton(onClick = {
                val branding = state.branding ?: return@OutlinedButton
                model.saveCards(if (field == "intro_asset") null else branding.introAsset,
                    if (field == "intro_asset") null else branding.introDuration,
                    if (field == "outro_asset") null else branding.outroAsset,
                    if (field == "outro_asset") null else branding.outroDuration)
            }, enabled = !state.busy && !reading) { Text(stringResource(R.string.clear_card)) }
        }
        if (cards) {
            Button(onClick = {
                val branding = state.branding ?: return@Button
                model.saveCards(branding.introAsset, if (branding.introAsset != null) state.drafts["intro_duration"]?.toDoubleOrNull() else null,
                    branding.outroAsset, if (branding.outroAsset != null) state.drafts["outro_duration"]?.toDoubleOrNull() else null)
            }, enabled = !state.busy && !reading && state.branding != null) { Text(stringResource(R.string.save_cards)) }
            TextButton(onClick = model::skipCards, enabled = !state.busy && !reading) { Text(stringResource(R.string.skip_cards)) }
        }
    }
}
@Composable private fun SectionHeadingForBranding(label: Int) { com.dojo.aisomedo.ui.SectionHeading(label) }

@Composable private fun BrandingPreview(model: AppViewModel, asset: String, label: Int) {
    var bitmap by remember(asset) { mutableStateOf<android.graphics.Bitmap?>(null) }
    var failed by remember(asset) { mutableStateOf(false) }
    var retry by remember(asset) { mutableIntStateOf(0) }
    LaunchedEffect(asset, retry) {
        try {
            failed = false
            require(asset.startsWith("branding/assets/"))
            val bytes = model.preview("/api/settings/branding/assets/" + asset.removePrefix("branding/assets/"))
            bitmap = withContext(Dispatchers.Default) {
                val options = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options)
                require(options.outWidth in 1..4096 && options.outHeight in 1..4096)
                options.inJustDecodeBounds = false
                options.inSampleSize = 1
                while (maxOf(options.outWidth, options.outHeight) / options.inSampleSize > 1024) options.inSampleSize *= 2
                BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options) ?: throw IllegalArgumentException("image")
            }
        } catch (e: CancellationException) { throw e }
        catch (_: Exception) { failed = true }
    }
    bitmap?.let { Image(it.asImageBitmap(), contentDescription = stringResource(R.string.image_preview, stringResource(label)), modifier = Modifier.fillMaxWidth().heightIn(max = 200.dp)) }
    if (failed) {
        Text(stringResource(R.string.preview_failed))
        TextButton(onClick = { retry++ }) { Text(stringResource(R.string.retry)) }
    }
}
