package com.dojo.aisomedo.ui

import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.unit.dp
import com.dojo.aisomedo.R

@Composable fun CollapsiblePanel(title: String, modifier: Modifier = Modifier,
    actions: @Composable RowScope.() -> Unit = {}, initiallyExpanded: Boolean = true, content: @Composable ColumnScope.() -> Unit) {
    var expanded by rememberSaveable { mutableStateOf(initiallyExpanded) }
    val holder = rememberSaveableStateHolder()
    val state = stringResource(if (expanded) R.string.panel_expanded else R.string.panel_collapsed)
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Top) {
            Text(title, style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f).semantics { heading() })
            if (expanded) actions()
            IconButton(onClick = { expanded = !expanded }, modifier = Modifier.semantics { stateDescription = state }) {
                Icon(if (expanded) Icons.Default.KeyboardArrowUp else Icons.Default.KeyboardArrowDown,
                    contentDescription = stringResource(if (expanded) R.string.panel_collapse else R.string.panel_expand, title))
            }
        }
        if (expanded) holder.SaveableStateProvider("body") {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp), content = content)
        }
    }
}
