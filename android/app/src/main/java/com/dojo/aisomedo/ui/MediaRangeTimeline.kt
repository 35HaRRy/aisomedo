package com.dojo.aisomedo.ui

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.dojo.aisomedo.R
import com.dojo.aisomedo.api.VideoRangeOut
import kotlin.math.round

internal fun timelineBound(value: Float, low: Double, high: Double): Double = when {
    value <= low.toFloat() -> low
    value >= high.toFloat() -> high
    else -> (round(value.toDouble() * 1000) / 1000).coerceIn(low, high)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun MediaRangeTimeline(duration: Double, ranges: List<VideoRangeOut>, disabled: Boolean,
    onChange: (List<VideoRangeOut>) -> Unit) {
    if (!duration.isFinite() || duration < 0.04) return
    val displayed = ranges.ifEmpty { listOf(VideoRangeOut(start = 0.0, end = duration)) }
    Column(Modifier.fillMaxWidth().padding(horizontal = 8.dp).testTag("media-timeline")) {
        Text(stringResource(R.string.media_timeline), style = MaterialTheme.typography.labelLarge)
        displayed.forEachIndexed { index, range ->
            val low = displayed.getOrNull(index - 1)?.end ?: 0.0
            val high = displayed.getOrNull(index + 1)?.start ?: duration
            RangeSlider(value = range.start.toFloat()..range.end.toFloat(), enabled = !disabled,
                valueRange = low.toFloat()..high.toFloat(), modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
                onValueChange = { value ->
                    val startChanged = value.start != range.start.toFloat()
                    val start = if (startChanged) timelineBound(value.start, low, range.end - 0.04) else range.start
                    val end = if (!startChanged) timelineBound(value.endInclusive, start + 0.04, high) else range.end
                    onChange(displayed.mapIndexed { i, existing -> if (i == index) VideoRangeOut(start = start, end = end) else existing })
                })
        }
    }
}
