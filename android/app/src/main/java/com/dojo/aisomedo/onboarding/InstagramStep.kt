package com.dojo.aisomedo.onboarding

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.dojo.aisomedo.AppViewModel
import com.dojo.aisomedo.R
import com.dojo.aisomedo.ui.statusLabel

@Composable fun InstagramStep(model: AppViewModel, openUrl: (String) -> Unit) {
    val state by model.state.collectAsStateWithLifecycle()
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    var active by remember { mutableStateOf(lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) }
    DisposableEffect(lifecycle) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_STOP) active = false
            if (event == Lifecycle.Event.ON_START) active = true
        }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer) }
    }
    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
        state.instagram?.let { Text(it.igUsername ?: stringResource(R.string.no_account)); Text(stringResource(statusLabel(it.health))) }
        InstagramTokenForm(state.busy, active, model::connectInstagramToken)
        OutlinedButton(onClick = { model.startOAuth(openUrl) }, enabled = !state.busy) { Text(stringResource(R.string.oauth_start)) }
        state.attempt?.let { attempt ->
            Text(stringResource(when (attempt.status) {
                "pending" -> R.string.oauth_pending; "completed" -> R.string.oauth_choose
                "selected" -> R.string.oauth_selected; else -> R.string.oauth_failed
            }))
            if (attempt.status == "completed") attempt.candidates.forEach { candidate ->
                OutlinedButton(onClick = { model.selectAccount(candidate.igUserId) }, enabled = !state.busy) {
                    Text(stringResource(R.string.oauth_select_account, candidate.igUsername))
                }
            }
            TextButton(onClick = model::checkOAuth, enabled = !state.busy) { Text(stringResource(R.string.oauth_check)) }
        }
    }
}

@Composable fun InstagramTokenForm(busy: Boolean, active: Boolean, onSubmit: (String) -> Unit) {
    var token by remember { mutableStateOf("") }
    LaunchedEffect(active) { if (!active) token = "" }
    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
        OutlinedTextField(token, { token = it }, label = { Text(stringResource(R.string.instagram_token)) },
            visualTransformation = PasswordVisualTransformation(), singleLine = true, enabled = !busy,
            modifier = Modifier.fillMaxWidth().testTag("instagram-token"))
        Button(onClick = { val value = token; token = ""; onSubmit(value) }, enabled = !busy && active && token.isNotBlank()) {
            Text(stringResource(R.string.instagram_connect))
        }
    }
}
