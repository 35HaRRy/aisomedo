package com.dojo.aisomedo.ui

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.dojo.aisomedo.R
import com.dojo.aisomedo.api.*
import kotlinx.serialization.json.*
import java.time.Instant

private val actorJson = Json { ignoreUnknownKeys = true }

fun activityActorLabel(actor: JsonElement): String? = when (actor) {
    is JsonPrimitive -> actor.takeIf { it.isString }?.content?.takeIf { it.isNotBlank() }
    is JsonObject -> runCatching { actorJson.decodeFromJsonElement<ClientRefOut>(actor).name.takeIf { it.isNotBlank() } }.getOrNull()
    else -> null
}

@Composable fun LastFetchedAt(fetchedAt: Long?, tag: String) {
    fetchedAt?.let { Text(stringResource(R.string.last_fetch, formattedTime(Instant.ofEpochMilli(it).toString())),
        modifier = Modifier.testTag(tag), style = MaterialTheme.typography.bodySmall) }
}
@Composable fun ActivityScreen(page: ActivityPageOut?, fetchedAt: Long?, busy: Boolean, onRefresh: () -> Unit) {
    Heading(R.string.activity)
    OutlinedButton(onClick = onRefresh, enabled = !busy) { Text(stringResource(R.string.refresh)) }
    LastFetchedAt(fetchedAt, "activity-fetched-at")
    if (page == null) Text(stringResource(R.string.cache_unavailable))
    else if (page.events.isEmpty()) Text(stringResource(R.string.activity_empty))
    else Column(Modifier.widthIn(max = 640.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        page.events.forEach { event ->
            Text(event.action, style = MaterialTheme.typography.titleMedium)
            Text(formattedTime(event.occurredAt), style = MaterialTheme.typography.bodySmall)
            Text(activityActorLabel(event.actor) ?: stringResource(R.string.activity_actor_unknown))
            HorizontalDivider()
        }
    }
}
