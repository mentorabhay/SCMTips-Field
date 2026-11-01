package com.scmtips.field.app.ui.homes

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
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
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * 3.1 Tower home (TowerHome.dc.html), under the shell's header: the check-in card while no site visit is open here
 * (it opens the first tower job, whose first step checks the location and the work permit; the home shows no GPS
 * or permit of its own), then the tower jobs. Empty: a mast drawing, one sentence, Refresh.
 */
@Composable
fun TowerHome(
    model: TowerHomeModel,
    canAct: Boolean,
    reduceMotion: Boolean,
    onOpenTask: (String) -> Unit,
    onRefresh: () -> Unit,
    modifier: Modifier = Modifier,
    contentPadding: PaddingValues = PaddingValues(16.dp),
) {
    LazyColumn(modifier.fillMaxSize(), contentPadding = contentPadding, verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item { HomeHeadline(model.headline, model.loading, onRefresh) }
        when {
            !model.linked -> item {
                EmptyState("Tower jobs appear here once this phone is linked to a Field site.", "Refresh", onRefresh, enabled = true) {
                    EmptyTowerArt(reduceMotion)
                }
            }
            model.empty -> item {
                EmptyState("No tower job is assigned to you right now. New jobs appear here by themselves.", "Refresh", onRefresh, enabled = true) {
                    EmptyTowerArt(reduceMotion)
                }
            }
        }
        val first = model.checkInTaskId
        if (first != null) item {
            if (model.checkedIn) {
                Row(
                    Modifier.fillMaxWidth().background(SuccessBg, CardShape).padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Glyph(GlyphKind.TICK, Good, size = 20.dp, stroke = 2.6f)
                    Text("Checked in on site", color = Good, fontSize = 15.sp, fontWeight = FontWeight.Bold)
                }
            } else {
                HomeCard(shape = RoundedCornerShape(20.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                        LocationPingArt(reduceMotion, desc = null)
                        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                            Text("Check in on site", color = Ink, fontSize = 17.sp, fontWeight = FontWeight.Bold)
                            Text("Not checked in. The first job checks your location and asks for your work permit number.",
                                color = Muted, fontSize = 14.sp, lineHeight = 20.sp)
                        }
                    }
                    GradientButton("Check in", { onOpenTask(first) }, enabled = canAct, height = 54.dp, modifier = Modifier.padding(top = 4.dp))
                }
            }
        }
        if (model.jobs.isNotEmpty()) {
            item { SectionLabel(if (model.checkedIn) "Your jobs on this site" else "After check-in") }
            item {
                Column(Modifier.fillMaxWidth().background(Surface, RoundedCornerShape(18.dp)).border(1.dp, Border, RoundedCornerShape(18.dp))) {
                    model.jobs.forEachIndexed { i, j ->
                        JobRow(j, canAct) { onOpenTask(j.taskId) }
                        if (i < model.jobs.lastIndex) Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp).heightIn(min = 1.dp).background(RowDivider))
                    }
                }
            }
        }
    }
}

@Composable
private fun JobRow(j: TowerJob, canAct: Boolean, onClick: () -> Unit) {
    val swap = j.letter == "S"
    Row(
        Modifier.fillMaxWidth().heightIn(min = 64.dp).clickable(enabled = canAct, role = Role.Button, onClickLabel = "Open ${j.title}", onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Box(Modifier.size(44.dp).background(if (swap) WarnBg else AccentTint, RoundedCornerShape(12.dp)), contentAlignment = Alignment.Center) {
            Text(j.letter, color = if (swap) SandboxInk else AccentInk, fontWeight = FontWeight.Bold, fontSize = 16.sp)
        }
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(j.title, color = Ink, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text(j.sub, color = Muted, fontSize = 13.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
        if (j.started) Tag("Started", AccentInk, AccentTint)
    }
}
