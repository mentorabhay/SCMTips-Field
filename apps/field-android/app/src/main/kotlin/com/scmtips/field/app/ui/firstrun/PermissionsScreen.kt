package com.scmtips.field.app.ui.firstrun

import android.os.Build
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.shell.PermissionStep
import com.scmtips.field.app.ui.homes.BrandStart
import com.scmtips.field.app.ui.homes.GradientButton
import com.scmtips.field.app.ui.homes.Ground
import com.scmtips.field.app.ui.homes.Ink
import com.scmtips.field.app.ui.homes.LinkButton
import com.scmtips.field.app.ui.homes.Muted
import androidx.compose.ui.graphics.Color

/**
 * 1.4 Permissions (Permissions.dc.html), one at a time, each saying why. "Allow" calls [onAllow] (the shell asks
 * Android) and moves on; "Not now" moves on without asking. After the last step, or when [steps] is empty (all
 * granted, or an Android version that grants them at install), [onDone].
 */
@Composable
fun PermissionsScreen(
    reduceMotion: Boolean,
    onAllow: (PermissionStep) -> Unit,
    onDone: () -> Unit,
    steps: List<PermissionStep> = PermissionPlan.steps(Build.VERSION.SDK_INT),
) {
    if (steps.isEmpty()) {
        LaunchedEffect(Unit) { onDone() }
        return
    }
    var index by rememberSaveable { mutableIntStateOf(0) }
    val i = index.coerceIn(0, steps.size - 1)
    val step = steps[i]
    fun advance() { PermissionPlan.after(steps, i)?.let { index = it } ?: onDone() }
    Column(
        Modifier.fillMaxSize().background(Ground).verticalScroll(rememberScrollState()).padding(start = 20.dp, end = 20.dp, top = 56.dp, bottom = 28.dp),
        verticalArrangement = Arrangement.spacedBy(24.dp),
    ) {
        val progress = PermissionPlan.progress(i, steps.size)
        Column(Modifier.semantics(mergeDescendants = true) { contentDescription = progress }, verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(progress, color = Muted, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                steps.indices.forEach { k ->
                    Box(Modifier.weight(1f).height(4.dp).background(if (k <= i) BrandStart else Color(0xFFDDE0E6), RoundedCornerShape(2.dp)))
                }
            }
        }
        Column(Modifier.fillMaxWidth().heightIn(min = 380.dp), horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(24.dp, Alignment.CenterVertically)) {
            PermissionArt(step, reduceMotion)
            Text(step.title, color = Ink, fontSize = 26.sp, lineHeight = 32.sp, fontWeight = FontWeight.Bold, modifier = Modifier.semantics { heading() })
            Text(step.why, color = Muted, fontSize = 17.sp, lineHeight = 25.sp, textAlign = TextAlign.Center, modifier = Modifier.widthIn(max = 320.dp))
        }
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            GradientButton(PermissionPlan.allowLabel(i, steps.size), { onAllow(step); advance() })
            LinkButton("Not now", { advance() }, color = Muted, modifier = Modifier.fillMaxWidth())
        }
    }
}
