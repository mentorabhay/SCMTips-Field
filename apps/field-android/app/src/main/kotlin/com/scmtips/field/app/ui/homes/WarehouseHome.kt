package com.scmtips.field.app.ui.homes

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.scmtips.field.app.home.CaseStart
import com.scmtips.field.app.home.SandboxStart
import com.scmtips.field.app.jobs.JobType
import com.scmtips.field.app.ui.CountShelfDialog

/**
 * 2.1 Warehouse home (WarehouseHome.dc.html), the content under the shell's header: the headline, NEXT UP (the
 * oldest open receipt, else a sandbox case, else the oldest other job) with its one main action, the four work tiles
 * with real counts, and on a sandbox site "Test at home". Empty: a drawing, one sentence, Refresh. With [canAct]
 * false every act button is disabled (the shell's view-only banner says why); nothing is invented.
 */
@Composable
fun WarehouseHome(
    model: WarehouseHomeModel,
    canAct: Boolean,
    reduceMotion: Boolean,
    onOpenTask: (String) -> Unit,
    onOpenStarter: (JobType) -> Unit,
    onStartCase: (CaseStart) -> Unit,
    onStartSandbox: (SandboxStart, String?) -> Unit,
    onRefresh: () -> Unit,
    modifier: Modifier = Modifier,
    contentPadding: PaddingValues = PaddingValues(start = 16.dp, end = 16.dp, top = 18.dp, bottom = 24.dp),
) {
    var askShelf by rememberSaveable { mutableStateOf(false) }
    if (askShelf) CountShelfDialog(onStart = { bin -> askShelf = false; onStartSandbox(SandboxStart.COUNT_SHELF, bin) }, onDismiss = { askShelf = false })
    LazyColumn(modifier.fillMaxSize(), contentPadding = contentPadding, verticalArrangement = Arrangement.spacedBy(16.dp)) {
        item { HomeHeadline(model.headline, model.loading, onRefresh) }
        when {
            !model.linked -> item {
                EmptyState("Your jobs appear here once this phone is linked to a Field site.", "Refresh", onRefresh, enabled = true) {
                    EmptyShelfArt(reduceMotion)
                }
            }
            model.empty -> item {
                EmptyState("Nothing is assigned to you right now. New jobs appear here by themselves.", "Refresh", onRefresh, enabled = true) {
                    EmptyShelfArt(reduceMotion)
                }
            }
        }
        model.nextUp?.let { n -> item { NextUpCard(n, model.sandbox, canAct, onOpenTask, onStartCase) } }
        if (model.tiles.isNotEmpty() && !model.empty) item {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                model.tiles.chunked(2).forEach { pair ->
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        pair.forEach { t -> Tile(t, canAct, Modifier.weight(1f)) { onOpenStarter(t.type) } }
                        if (pair.size == 1) Box(Modifier.weight(1f))
                    }
                }
            }
        }
        if (model.cases.isNotEmpty() || model.sandboxStarts.isNotEmpty()) item {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                SectionLabel("Test at home")
                model.cases.chunked(2).forEach { pair ->
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        pair.forEach { c -> Starter(c.label, c.sub, canAct, Modifier.weight(1f)) { onStartCase(c) } }
                        if (pair.size == 1) Box(Modifier.weight(1f))
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    model.sandboxStarts.forEach { s ->
                        Starter(s.label, s.sub, canAct, Modifier.weight(1f)) {
                            if (s == SandboxStart.COUNT_SHELF) askShelf = true else onStartSandbox(s, null)
                        }
                    }
                }
            }
        }
    }
}

/** The headline of a home ("6 tasks today") with Refresh, or a spinner while loading. */
@Composable
internal fun HomeHeadline(text: String, loading: Boolean, onRefresh: () -> Unit) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(text, color = Ink, fontSize = 22.sp, lineHeight = 28.sp, fontWeight = FontWeight.Bold,
            modifier = Modifier.weight(1f).semantics { heading() })
        if (loading) Box(Modifier.size(MinTouch), contentAlignment = Alignment.Center) {
            CircularProgressIndicator(Modifier.size(22.dp), color = BrandStart, strokeWidth = 2.5.dp)
        } else LinkButton("Refresh", onRefresh, size = 14)
    }
}

@Composable
private fun NextUpCard(n: NextUp, sandbox: Boolean, canAct: Boolean, onOpenTask: (String) -> Unit, onStartCase: (CaseStart) -> Unit) {
    val (title, sub, cta) = when (n) {
        is NextUp.Task -> Triple(n.title, n.sub, when {
            n.started -> "Carry on"
            n.look -> "Start · say “look”"
            else -> "Start"
        })
        is NextUp.Case -> Triple(n.start.label, n.start.sub, "Start · say “look”")
    }
    HomeCard(shape = RoundedCornerShape(20.dp), padding = PaddingValues(18.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text("NEXT UP", color = AccentInk, fontSize = 13.sp, fontWeight = FontWeight.Bold, letterSpacing = 0.6.sp, modifier = Modifier.weight(1f))
            if (sandbox) Tag("Sandbox", SandboxInk, WarnBg)
        }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            Box(Modifier.size(52.dp).background(AccentTint, RoundedCornerShape(14.dp)), contentAlignment = Alignment.Center) {
                Glyph(GlyphKind.BOX, AccentInk, size = 26.dp)
            }
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(title, color = Ink, fontSize = 18.sp, fontWeight = FontWeight.Bold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Text(sub, color = Muted, fontSize = 14.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
        }
        GradientButton(cta, {
            when (n) {
                is NextUp.Task -> onOpenTask(n.taskId)
                is NextUp.Case -> onStartCase(n.start)
            }
        }, enabled = canAct, height = 52.dp, modifier = Modifier.padding(top = 4.dp))
    }
}

@Composable
private fun Tile(t: WorkTile, canAct: Boolean, modifier: Modifier, onClick: () -> Unit) {
    HomeCard(modifier.heightIn(min = 92.dp), onClick = onClick, enabled = canAct, shape = RoundedCornerShape(18.dp), padding = PaddingValues(14.dp),
        onClickLabel = "Open ${t.label}") {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(t.label, color = Ink, fontSize = 16.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
            CountBadge(t.count)
        }
        Text(t.sub, color = Muted, fontSize = 13.sp)
    }
}

@Composable
private fun Starter(label: String, sub: String, canAct: Boolean, modifier: Modifier, onClick: () -> Unit) {
    HomeCard(modifier, onClick = onClick, enabled = canAct, dashed = true, shape = ButtonShape, padding = PaddingValues(12.dp)) {
        Text(label, color = Ink, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
        Text(sub, color = Muted, fontSize = 12.sp, lineHeight = 16.sp)
    }
}
